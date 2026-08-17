"""Independent fail-closed re-review probes for t_63866ca7."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core

NOW = 2_000_000_000


class ReviewProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "kanban.db"
        self.key = b"independent-review-key" * 2
        self.req = core.make_request("t_rereview", 128, "Q" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)", ("t_rereview", "running", None, core.digest(self.req)))
        db.execute("insert into task_runs values(?,?,?,?)", (128, "t_rereview", "running", None))
        db.commit()
        db.close()
        self.approvals = self.root / "approvals"
        self.ledger = self.root / "ledger"
        self.lock = self.root / "lock"
        core.approve(self.req, db=self.db, key=self.key, approvals=self.approvals,
                     captain_uid=1000, now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, backend):
        return core.execute(self.req, db=self.db, key=self.key, approvals=self.approvals,
                            ledger=self.ledger, lock=self.lock, now=NOW, backend=backend)

    def test_complete_tail_truncation_is_detected(self):
        core.append_chain(self.ledger, self.key, core._event(self.req, "one", NOW))
        core.append_chain(self.ledger, self.key, core._event(self.req, "two", NOW + 1))
        first = self.ledger.read_bytes().splitlines(keepends=True)[0]
        self.ledger.write_bytes(first)
        with self.assertRaisesRegex(core.Rejected, "checkpoint-mismatch"):
            core.verify_chain(self.ledger, self.key)

    def test_precheck_failure_does_not_spend_authority_or_call_rollback(self):
        calls = []
        class Backend:
            def check_pre(inner, request):
                calls.append("pre")
                raise core.Rejected("preflight failed")
            def mutate(inner, request):
                calls.append("mutate")
            def health(inner, request):
                calls.append("health")
                return {"ok": True}
            def rollback(inner, request):
                calls.append("rollback")
                return {"no_mutation_proven": False}
        result = self.execute(Backend())
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["pre"])
        self.assertEqual(core.verify_chain(self.ledger, self.key)[0]["phase"], "preflight_rejected")

    def test_task_finishing_after_precheck_prevents_mutation(self):
        calls = []
        outer = self
        class Backend:
            def check_pre(inner, request):
                calls.append("pre")
                db = sqlite3.connect(outer.db)
                db.execute("update tasks set status='done',completed_at=?", (NOW,))
                db.execute("update task_runs set status='done',ended_at=?", (NOW,))
                db.commit()
                db.close()
            def mutate(inner, request):
                calls.append("mutate")
            def health(inner, request):
                calls.append("health")
                return {"ok": True}
            def rollback(inner, request):
                calls.append("rollback")
        with self.assertRaisesRegex(core.Rejected, "inactive-task-run"):
            self.execute(Backend())
        self.assertEqual(calls, ["pre"])

    def test_result_append_crash_records_recovery_required(self):
        calls = []
        class Backend:
            def check_pre(inner, request): calls.append("pre")
            def mutate(inner, request): calls.append("mutate")
            def health(inner, request): calls.append("health"); return {"ok": True}
            def rollback(inner, request): calls.append("rollback")
        real = core.append_chain
        count = 0
        def crash(path, key, body):
            nonlocal count
            count += 1
            if body.get("phase") == "committed":
                raise OSError("deterministic result append failure")
            return real(path, key, body)
        with mock.patch.object(core, "append_chain", side_effect=crash):
            result = self.execute(Backend())
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["pre", "mutate", "health"])
        records = core.verify_chain(self.ledger, self.key)
        self.assertEqual(records[-1]["phase"], "recovery_required")
        self.assertIn("health_passed", [record.get("phase") for record in records])


if __name__ == "__main__":
    unittest.main()
