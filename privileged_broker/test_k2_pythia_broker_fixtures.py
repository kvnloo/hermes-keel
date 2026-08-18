"""K2 Pythia fault fixtures for the real privileged-broker state machine.

The oracles in this file are intentionally derived from externally observable
state (backend call order, authenticated ledger records, and SQLite visibility),
not from implementation return values alone.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core

NOW = 2_000_000_000
CORE_SHA256 = "42063a07afcdc70448d9f67cfaee2975813a5e8f1ae796836a5cee6878f01ac9"


class RecordingBackend:
    def __init__(self, *, pre_error: Exception | None = None, health_ok: bool = True,
                 mutate_entered: threading.Event | None = None,
                 mutate_release: threading.Event | None = None):
        self.calls: list[str] = []
        self.pre_error = pre_error
        self.health_ok = health_ok
        self.mutate_entered = mutate_entered
        self.mutate_release = mutate_release

    def check_pre(self, request):
        self.calls.append("pre")
        if self.pre_error:
            raise self.pre_error

    def mutate(self, request):
        self.calls.append("mutate")
        if self.mutate_entered:
            self.mutate_entered.set()
        if self.mutate_release:
            if not self.mutate_release.wait(3):
                raise RuntimeError("fixture release timeout")

    def health(self, request):
        self.calls.append("health")
        return {"ok": self.health_ok, "fixture": "k2"}

    def rollback(self, request):
        self.calls.append("rollback")
        return {"restored": True}


class Harness:
    def __init__(self, module=core):
        self.module = module
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "kanban.db"
        self.key = b"k2-pythia-fixture-key-32-bytes!"[:32]
        self.request = module.make_request("t_k2fixture", 202, "N" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)",
                   ("t_k2fixture", "running", None, module.digest(self.request)))
        db.execute("insert into task_runs values(?,?,?,?)",
                   (202, "t_k2fixture", "running", None))
        db.commit()
        db.close()
        self.approvals = self.root / "approvals.jsonl"
        self.ledger = self.root / "ledger.jsonl"
        self.lock = self.root / "execute.lock"

    def close(self):
        self.temp.cleanup()

    def approve(self):
        return self.module.approve(
            self.request, db=self.db, key=self.key, approvals=self.approvals,
            captain_uid=1000, now=NOW,
        )

    def execute(self, backend):
        return self.module.execute(
            self.request, db=self.db, key=self.key, approvals=self.approvals,
            ledger=self.ledger, lock=self.lock, now=NOW, backend=backend,
        )

    def phases(self):
        return [record.get("phase") for record in self.module.verify_chain(self.ledger, self.key)]


def load_mutant(old: str, new: str) -> types.ModuleType:
    source = Path(core.__file__).read_text()
    if source.count(old) != 1:
        raise AssertionError(f"mutation anchor count is {source.count(old)}, expected one")
    root = Path(tempfile.mkdtemp(prefix="keel-k2-mutant-"))
    path = root / "core_mutant.py"
    path.write_text(source.replace(old, new))
    name = f"core_k2_mutant_{hashlib.sha256(new.encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class K2BrokerFixtures(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_00_production_sentinel_is_unchanged(self):
        self.assertEqual(hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(), CORE_SHA256)

    def test_preflight_rejection_happens_before_spend_and_is_retryable(self):
        self.h.approve()
        rejected = RecordingBackend(pre_error=core.Rejected("fixture-preflight"))
        result = self.h.execute(rejected)
        self.assertFalse(result["ok"])
        self.assertEqual(rejected.calls, ["pre"])
        self.assertEqual(self.h.phases(), ["preflight_rejected"])

        healthy = RecordingBackend()
        result = self.h.execute(healthy)
        self.assertTrue(result["ok"])
        self.assertEqual(healthy.calls, ["pre", "mutate", "health"])
        self.assertEqual(self.h.phases().count("consumed"), 1)

    def test_task_run_and_approved_envelope_freshness_are_all_required(self):
        self.h.approve()
        db = sqlite3.connect(self.h.db)
        db.execute("update task_runs set status='done',ended_at=? where id=202", (NOW,))
        db.commit()
        db.close()
        backend = RecordingBackend()
        with self.assertRaisesRegex(core.Rejected, "inactive-task-run"):
            self.h.execute(backend)
        # Read-only live preflight may run before the canonical authority fence;
        # no mutation is permitted for stale task/run authority.
        self.assertEqual(backend.calls, ["pre"])

        db = sqlite3.connect(self.h.db)
        db.execute("update task_runs set status='running',ended_at=null where id=202")
        db.commit()
        db.close()
        self.h.request["nonce"] = "X" * 32
        with self.assertRaisesRegex(core.Rejected, "missing-or-ambiguous-approval"):
            self.h.execute(backend)
        self.assertEqual(backend.calls, ["pre"])

    def test_nonce_replay_is_spent_before_any_second_mutation(self):
        self.h.approve()
        first = RecordingBackend()
        self.assertTrue(self.h.execute(first)["ok"])
        second = RecordingBackend()
        with self.assertRaisesRegex(core.Rejected, "replay"):
            self.h.execute(second)
        self.assertEqual(second.calls, [])
        self.assertEqual(self.h.phases().count("consumed"), 1)

    def test_mutation_race_is_serialized_by_canonical_sqlite_fence(self):
        self.h.approve()
        entered = threading.Event()
        release = threading.Event()
        backend = RecordingBackend(mutate_entered=entered, mutate_release=release)
        execution: dict[str, object] = {}

        def run_execute():
            try:
                execution["result"] = self.h.execute(backend)
            except BaseException as exc:  # surfaced in the parent assertion
                execution["error"] = exc

        thread = threading.Thread(target=run_execute)
        thread.start()
        self.assertTrue(entered.wait(3))
        contender = sqlite3.connect(self.h.db, timeout=0, isolation_level=None)
        with self.assertRaises(sqlite3.OperationalError):
            contender.execute("begin immediate")
        contender.close()
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertNotIn("error", execution)
        self.assertTrue(execution["result"]["ok"])

        # The broker rolled its authority transaction back; it did not acquire
        # the right to alter canonical task state.
        db = sqlite3.connect(self.h.db)
        row = db.execute("select status,completed_at from tasks where id='t_k2fixture'").fetchone()
        db.close()
        self.assertEqual(row, ("running", None))

    def test_crashes_before_and_after_mutation_have_distinct_recovery_evidence(self):
        self.h.approve()
        real_append = core.append_chain

        def crash_after_consumed(path, key, record):
            written = real_append(path, key, record)
            if record.get("phase") == "consumed":
                raise RuntimeError("fixture-crash-after-consume")
            return written

        before = RecordingBackend()
        with mock.patch.object(core, "append_chain", side_effect=crash_after_consumed):
            with self.assertRaisesRegex(RuntimeError, "after-consume"):
                self.h.execute(before)
        self.assertEqual(before.calls, ["pre"])
        self.assertIn("consumed", self.h.phases())
        with self.assertRaisesRegex(core.Rejected, "replay"):
            self.h.execute(RecordingBackend())

        other = Harness()
        self.addCleanup(other.close)
        other.approve()

        def crash_after_health(path, key, record):
            if record.get("phase") == "health_passed":
                raise RuntimeError("fixture-crash-after-mutation")
            return real_append(path, key, record)

        after = RecordingBackend()
        with mock.patch.object(core, "append_chain", side_effect=crash_after_health):
            result = other.execute(after)
        self.assertFalse(result["ok"])
        self.assertTrue(result["rollback_ok"])
        self.assertEqual(after.calls, ["pre", "mutate", "health", "rollback"])
        self.assertEqual(other.phases()[-2:], ["rollback_started", "rollback_verified"])

    def test_ledger_framing_truncation_checkpoint_and_atomic_publication(self):
        event = core._phase(self.h.request, "prepared", NOW)
        core.append_chain(self.h.ledger, self.h.key, event)
        generation = self.h.ledger.read_bytes()

        self.h.ledger.write_bytes(generation[:-1])
        with self.assertRaisesRegex(core.Rejected, "partial-ledger-frame"):
            core.verify_chain(self.h.ledger, self.h.key)
        self.h.ledger.write_bytes(generation)

        rows = self.h.ledger.read_text().splitlines()
        tip = json.loads(rows[-1])
        tip["terminal_record_hash"] = "0" * 64
        self.h.ledger.write_text("\n".join([*rows[:-1], json.dumps(tip)]) + "\n")
        with self.assertRaisesRegex(core.Rejected, "checkpoint"):
            core.verify_chain(self.h.ledger, self.h.key)
        self.h.ledger.write_bytes(generation)

        with mock.patch.object(core.os, "replace", side_effect=OSError("fixture-publish-crash")):
            with self.assertRaisesRegex(OSError, "publish-crash"):
                core.append_chain(self.h.ledger, self.h.key,
                                  core._phase(self.h.request, "consumed", NOW))
        self.assertEqual(self.h.ledger.read_bytes(), generation)
        self.assertEqual(len(core.verify_chain(self.h.ledger, self.h.key)), 1)
        self.assertEqual(list(self.h.root.glob(".ledger.jsonl.*.tmp")), [])

    def test_known_fault_mutations_are_genuinely_red(self):
        mutants = [
            (
                "            backend.check_pre(req)\n",
                "            None  # K2 mutant: bypass preflight\n",
                self._oracle_preflight_before_mutation,
            ),
            (
                "        if raw and not raw.endswith(b\"\\n\"):\n            raise Rejected(\"partial-ledger-frame\")\n",
                "        if False:  # K2 mutant: accept torn final frame\n            raise Rejected(\"partial-ledger-frame\")\n",
                self._oracle_torn_frame_rejected,
            ),
            (
                "        spent = {\"consumed\", \"mutation_started\", \"health_passed\", \"committed\", \"rollback_started\",\n",
                "        spent = {\"mutation_started\", \"health_passed\", \"committed\", \"rollback_started\",\n",
                self._oracle_consumed_is_spent,
            ),
        ]
        for old, new, oracle in mutants:
            with self.subTest(mutation=new.strip()):
                mutant = load_mutant(old, new)
                self.assertTrue(oracle(core), "current implementation must be GREEN")
                self.assertFalse(oracle(mutant), "known mutation must produce genuine RED")

    @staticmethod
    def _oracle_preflight_before_mutation(module):
        h = Harness(module)
        try:
            h.approve()
            backend = RecordingBackend(pre_error=module.Rejected("red"))
            try:
                h.execute(backend)
            except module.Rejected:
                pass
            return backend.calls == ["pre"] and "mutate" not in backend.calls
        finally:
            h.close()

    @staticmethod
    def _oracle_torn_frame_rejected(module):
        h = Harness(module)
        try:
            module.append_chain(h.ledger, h.key, module._phase(h.request, "prepared", NOW))
            h.ledger.write_bytes(h.ledger.read_bytes()[:-1])
            try:
                module.verify_chain(h.ledger, h.key)
            except module.Rejected:
                return True
            return False
        finally:
            h.close()

    @staticmethod
    def _oracle_consumed_is_spent(module):
        h = Harness(module)
        try:
            h.approve()
            real_append = module.append_chain

            def crash(path, key, record):
                written = real_append(path, key, record)
                if record.get("phase") == "consumed":
                    raise RuntimeError("red")
                return written

            with mock.patch.object(module, "append_chain", side_effect=crash):
                try:
                    h.execute(RecordingBackend())
                except RuntimeError:
                    pass
            backend = RecordingBackend()
            try:
                h.execute(backend)
            except module.Rejected:
                return backend.calls == []
            return False
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
