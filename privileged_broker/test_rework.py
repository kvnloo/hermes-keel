"""Regression tests closing adversarial findings F-001 through F-005."""
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core

NOW = 2_000_000_000


class FailingBackend:
    def check_pre(self, request):
        pass

    def mutate(self, request):
        raise core.Rejected("mutation failed")

    def rollback(self, request):
        raise core.Rejected('{"failure":"rollback-restart","status":7,"stderr":"exact failure\\n"}')


class ReworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "kanban.db"
        self.key = b"ledger-key" * 4
        self.req = core.make_request("t_rework", 105, "R" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)", ("t_rework", "running", None, core.digest(self.req)))
        db.execute("insert into task_runs values(?,?,?,?)", (105, "t_rework", "running", None))
        db.commit()
        db.close()
        self.approvals = self.root / "approvals"
        self.ledger = self.root / "ledger"
        self.lock = self.root / "lock"

    def tearDown(self):
        self.temp.cleanup()

    def approve(self):
        core.approve(self.req, db=self.db, key=self.key, approvals=self.approvals,
                     captain_uid=1000, now=NOW)

    def execute(self, backend):
        return core.execute(self.req, db=self.db, key=self.key, approvals=self.approvals,
                            ledger=self.ledger, lock=self.lock, now=NOW, backend=backend)

    def test_f001_rollback_failure_preserves_exact_status_and_never_claims_success(self):
        self.approve()
        result = self.execute(FailingBackend())
        self.assertFalse(result["ok"])
        self.assertFalse(result["rollback_ok"])
        self.assertIn('"status":7', result["rollback_error"]["message"])
        self.assertIn("exact failure\\n", result["rollback_error"]["message"])
        core.verify_chain(self.ledger, self.key)

    def test_f002_complete_pre_state_is_bound_and_drift_rejected_before_write(self):
        self.assertEqual(set(self.req["expected_pre_state"]), core.PRE_STATE_KEYS)
        backend = core.OllamaBackend()
        drift = dict(self.req["expected_pre_state"])
        drift["fragment_sha256"] = "f" * 64
        with mock.patch.object(backend, "capture_pre_state", return_value=drift):
            with self.assertRaisesRegex(core.Rejected, "pre-mutation-drift"):
                backend.mutate(self.req)

    def test_f003_public_unknown_and_duplicate_runtime_fail_closed(self):
        backend = core.OllamaBackend()
        state = dict(self.req["expected_pre_state"])
        state["process_executable"] = core.NEW_BINARY
        state["process_sha256"] = core.NEW_SHA256
        state["version"] = core.NEW_VERSION
        state["daemon_pids"] = [4242]
        for listeners in (
            [{"address": "0.0.0.0", "port": core.PORT, "pid": 4242}],
            [{"address": "127.0.0.1", "port": core.PORT, "pid": 4242},
             {"address": "::1", "port": core.PORT, "pid": 9999}],
            [],
        ):
            state["listeners"] = listeners
            with self.assertRaises(core.Rejected):
                backend._assert_local_unique(state, core.NEW_BINARY, core.NEW_SHA256, core.NEW_VERSION)
        state["listeners"] = [{"address": "127.0.0.1", "port": core.PORT, "pid": 4242}]
        state["daemon_pids"] = [4242, 9999]
        with self.assertRaisesRegex(core.Rejected, "duplicate-or-unknown-daemon"):
            backend._assert_local_unique(state, core.NEW_BINARY, core.NEW_SHA256, core.NEW_VERSION)
        with self.assertRaisesRegex(core.Rejected, "unknown-cuda-telemetry"):
            backend._cuda_evidence(-1)

    def test_f005_chain_detects_edit_truncation_reorder_and_wrong_key(self):
        first = core.append_chain(self.ledger, self.key, core._event(self.req, "authorization-consumed", NOW))
        core.append_chain(self.ledger, self.key, {**core._event(self.req, "operation-result", NOW + 1), "ok": False})
        self.assertEqual(len(core.verify_chain(self.ledger, self.key)), 2)
        with self.assertRaisesRegex(core.Rejected, "ledger-chain-corrupt"):
            core.verify_chain(self.ledger, b"wrong" * 8)
        rows = self.ledger.read_text().splitlines()
        changed = json.loads(rows[0]); changed["at"] += 1
        self.ledger.write_text(json.dumps(changed) + "\n" + rows[1] + "\n")
        with self.assertRaisesRegex(core.Rejected, "ledger-chain-corrupt"):
            core.verify_chain(self.ledger, self.key)
        self.assertEqual(first["sequence"], 1)

    def test_f004_v1_builder_without_explicit_runtime_is_retired(self):
        package = self.root / "package"
        script = Path(__file__).with_name("build-package.sh")
        completed = subprocess.run([str(script), str(package)], capture_output=True, text=True, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exact reviewed Ollama runtime binary required", completed.stderr)
        self.assertFalse(package.exists())


if __name__ == "__main__":
    unittest.main()
