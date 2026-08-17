"""Independent adversarial regression probes for the privileged broker review."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from privileged_broker import core


NOW = 2_000_000_000


class Backend:
    def __init__(self, rollback_error=False):
        self.calls = []
        self.rollback_error = rollback_error

    def check_pre(self, request):
        self.calls.append("pre")

    def mutate(self, request):
        self.calls.append("mutate")

    def health(self, request):
        self.calls.append("health")
        return {"ok": False}

    def rollback(self, request):
        self.calls.append("rollback")
        if self.rollback_error:
            raise RuntimeError("rollback failed")


class AdversarialReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "kanban.db"
        self.key = b"review-key" * 4
        self.request = core.make_request("t_review", 104, "N" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)", ("t_review", "running", None, core.digest(self.request)))
        db.execute("insert into task_runs values(?,?,?,?)", (104, "t_review", "running", None))
        db.commit()
        db.close()
        self.approvals = self.root / "approvals.jsonl"
        self.ledger = self.root / "ledger.jsonl"
        self.lock = self.root / "execute.lock"

    def tearDown(self):
        self.temp.cleanup()

    def approve(self):
        return core.approve(self.request, db=self.db, key=self.key, approvals=self.approvals,
                            captain_uid=1000, now=NOW)

    def execute(self, backend):
        return core.execute(self.request, db=self.db, key=self.key, approvals=self.approvals,
                            ledger=self.ledger, lock=self.lock, now=NOW, backend=backend)

    def test_duplicate_valid_approval_is_ambiguous(self):
        receipt = self.approve()
        with self.approvals.open("a") as stream:
            stream.write(json.dumps(receipt) + "\n")
        with self.assertRaisesRegex(core.Rejected, "missing-or-ambiguous"):
            self.execute(Backend())

    def test_expiry_cannot_be_extended_after_approval(self):
        self.approve()
        self.request["expires_at"] += 1
        with self.assertRaises(core.Rejected):
            self.execute(Backend())

    def test_wrong_task_and_run_are_not_substitutable(self):
        self.approve()
        for field, value in (("requester_task", "t_other"), ("requester_run", 105)):
            changed = dict(self.request)
            changed[field] = value
            with self.assertRaises(core.Rejected):
                core.execute(changed, db=self.db, key=self.key, approvals=self.approvals,
                             ledger=self.ledger, lock=self.lock, now=NOW, backend=Backend())

    def test_rollback_exception_is_fail_closed_and_recorded(self):
        self.approve()
        result = self.execute(Backend(rollback_error=True))
        self.assertFalse(result["ok"])
        self.assertFalse(result["rollback_ok"])
        records = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertIn("consumed", [record.get("phase") for record in records])

    def test_malformed_ledger_blocks_execution(self):
        self.approve()
        self.ledger.write_text("not-json\n")
        with self.assertRaisesRegex(core.Rejected, "malformed-ledger"):
            self.execute(Backend())


if __name__ == "__main__":
    unittest.main()
