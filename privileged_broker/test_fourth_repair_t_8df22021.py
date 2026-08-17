"""Bounded fence and atomic-generation regressions for t_8df22021."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core

NOW = 2_000_000_000


class FourthRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "kanban.db"
        self.key = b"fourth-repair-key" * 2
        self.req = core.make_request("t_fourth", 140, "F" * 32, NOW)
        db = sqlite3.connect(self.db)
        db.executescript(
            "create table tasks(id text,status text,completed_at int,body text);"
            "create table task_runs(id int,task_id text,status text,ended_at int);"
            "create table task_comments(task_id text,body text);"
        )
        db.execute("insert into tasks values(?,?,?,?)", ("t_fourth", "running", None, core.digest(self.req)))
        db.execute("insert into task_runs values(?,?,?,?)", (140, "t_fourth", "running", None))
        db.commit()
        db.close()
        self.ledger = self.root / "ledger"

    def tearDown(self):
        self.temp.cleanup()

    def test_terminal_before_fence_rejected(self):
        db = sqlite3.connect(self.db)
        db.execute("update tasks set status='done',completed_at=?", (NOW,))
        db.commit(); db.close()
        with self.assertRaisesRegex(core.Rejected, "inactive-task-run"):
            core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))

    def test_duplicate_and_concurrent_revocation_fail_closed(self):
        fence, deadline = core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))
        try:
            with self.assertRaisesRegex(core.Rejected, "fence-unavailable"):
                core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))
            writer = sqlite3.connect(self.db, timeout=0)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    writer.execute("update tasks set status='done'")
            finally:
                writer.close()
            core._validate_mutation_fence(fence, deadline, self.req, core.digest(self.req))
        finally:
            fence.rollback(); fence.close()

    def test_expired_fence_rejected(self):
        fence, _ = core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))
        try:
            with self.assertRaisesRegex(core.Rejected, "fence-expired"):
                core._validate_mutation_fence(fence, -1, self.req, core.digest(self.req))
        finally:
            fence.rollback(); fence.close()

    def test_stale_fence_releases_on_connection_close(self):
        fence, _ = core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))
        fence.close()
        replacement, _ = core._acquire_mutation_fence(self.db, self.req, core.digest(self.req))
        replacement.rollback(); replacement.close()

    def test_unavailable_board_rejected(self):
        with self.assertRaisesRegex(core.Rejected, "unsafe-board"):
            core._acquire_mutation_fence(self.root / "missing.db", self.req, core.digest(self.req))

    def test_snapshot_write_and_fsync_failures_leave_previous_generation(self):
        core.append_chain(self.ledger, self.key, core._event(self.req, "one", NOW))
        prior = self.ledger.read_bytes()
        for target in ("write", "fsync"):
            original = getattr(os, target)
            calls = 0
            def fail(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected " + target)
                return original(*args, **kwargs)
            with mock.patch.object(os, target, side_effect=fail):
                with self.assertRaises(OSError):
                    core.append_chain(self.ledger, self.key, core._event(self.req, "two", NOW + 1))
            self.assertEqual(self.ledger.read_bytes(), prior)
            self.assertEqual(len(core.verify_chain(self.ledger, self.key)), 1)

    def test_corruption_truncation_and_tip_rollback_fail_closed(self):
        core.append_chain(self.ledger, self.key, core._event(self.req, "one", NOW))
        core.append_chain(self.ledger, self.key, core._event(self.req, "two", NOW + 1))
        rows = self.ledger.read_text().splitlines()
        for damaged in (rows[:-1], rows[:-2], [rows[0], rows[-1]]):
            self.ledger.write_text("\n".join(damaged) + "\n")
            with self.assertRaises(core.Rejected):
                core.verify_chain(self.ledger, self.key)
            self.ledger.write_text("\n".join(rows) + "\n")

    def test_snapshot_tip_binds_generation(self):
        core.append_chain(self.ledger, self.key, core._event(self.req, "one", NOW))
        tip = json.loads(self.ledger.read_text().splitlines()[-1])
        self.assertEqual(tip["type"], "ledger-snapshot-tip")
        self.assertEqual(tip["generation"], 1)


if __name__ == "__main__":
    unittest.main()
