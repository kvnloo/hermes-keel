"""Independent P0 crash/race probes for third review t_b3b69de5."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core

NOW = 2_000_000_000


class ThirdReviewP0Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "kanban.db"
        self.key = b"third-review-domain-key" * 2
        self.req = core.make_request("t_thirdreview", 136, "R" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)",
                   ("t_thirdreview", "running", None, core.digest(self.req)))
        db.execute("insert into task_runs values(?,?,?,?)", (136, "t_thirdreview", "running", None))
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

    def finish_task(self):
        db = sqlite3.connect(self.db)
        db.execute("update tasks set status='done',completed_at=?", (NOW,))
        db.execute("update task_runs set status='done',ended_at=?", (NOW,))
        db.commit()
        db.close()

    def test_terminal_race_after_mutation_started_record_prevents_mutation(self):
        calls = []
        outer = self

        class Backend:
            def check_pre(inner, request): calls.append("pre")
            def mutate(inner, request): calls.append("mutate")
            def health(inner, request): calls.append("health"); return {"ok": True}
            def rollback(inner, request): calls.append("rollback"); return {"ok": True}

        real = core.append_chain

        def finish_after_record(path, key, body):
            record = real(path, key, body)
            if body.get("phase") == "mutation_started":
                outer.finish_task()
            return record

        with mock.patch.object(core, "append_chain", side_effect=finish_after_record):
            result = self.execute(Backend())
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["pre"])
        self.assertEqual(core.verify_chain(self.ledger, self.key)[-1]["phase"], "recovery_required")

    def test_health_generation_crash_rolls_back_and_reconciles(self):
        calls = []

        class Backend:
            def check_pre(inner, request): calls.append("pre")
            def mutate(inner, request): calls.append("mutate")
            def health(inner, request): calls.append("health"); return {"ok": True}
            def rollback(inner, request): calls.append("rollback"); return {"ok": True}

        real = core._atomic_write
        checkpoint_writes = 0

        def fail_health_checkpoint(path, payload):
            nonlocal checkpoint_writes
            checkpoint_writes += 1
            if checkpoint_writes == 4:
                raise OSError("crash after durable health record, before checkpoint")
            return real(path, payload)

        with mock.patch.object(core, "_atomic_write", side_effect=fail_health_checkpoint):
            result = self.execute(Backend())
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["pre", "mutate", "health", "rollback"])
        self.assertEqual(core.verify_chain(self.ledger, self.key)[-1]["phase"], "rollback_verified")

    def test_committed_generation_crash_writes_recovery_record(self):
        calls = []

        class Backend:
            def check_pre(inner, request): calls.append("pre")
            def mutate(inner, request): calls.append("mutate")
            def health(inner, request): calls.append("health"); return {"ok": True}
            def rollback(inner, request): calls.append("rollback"); return {"ok": True}

        real = core._atomic_write
        checkpoint_writes = 0

        def fail_commit_checkpoint(path, payload):
            nonlocal checkpoint_writes
            checkpoint_writes += 1
            if checkpoint_writes == 5:
                raise OSError("crash after durable commit record, before checkpoint")
            return real(path, payload)

        with mock.patch.object(core, "_atomic_write", side_effect=fail_commit_checkpoint):
            result = self.execute(Backend())
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["pre", "mutate", "health"])
        self.assertEqual(core.verify_chain(self.ledger, self.key)[-1]["phase"], "recovery_required")


if __name__ == "__main__":
    unittest.main()