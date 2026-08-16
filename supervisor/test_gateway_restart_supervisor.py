import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from supervisor import gateway_restart_supervisor as sup

NOW = 2_000_000_000
EXECUTE_BODY = (
    "Captain explicitly authorized restarting the Telegram gateway. "
    "Restart exactly hermes-gateway.service for the Level 0B probe."
)
BUILD_BODY = (
    "This task establishes the supervisor only; do not perform the actual gateway restart. "
    "hermes-gateway.service is the fixed target."
)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        self.db = self.root / "kanban.db"
        self.log = self.root / "receipts.jsonl"
        db = sqlite3.connect(self.db)
        db.execute(
            "create table tasks(id text primary key,title text,body text,status text,completed_at integer)"
        )
        db.execute(
            "insert into tasks values(?,?,?,?,?)",
            ("t_235ade89", "Run gateway restart probe", EXECUTE_BODY, "running", None),
        )
        db.execute(
            "insert into tasks values(?,?,?,?,?)",
            ("t_db2e6a35", "Build supervisor", BUILD_BODY, "running", None),
        )
        db.commit()
        db.close()
        self.base = {
            "version": 1,
            "task_id": "t_235ade89",
            "nonce": "A" * 32,
            "service": sup.SERVICE,
            "board": "zer0-company",
            "created_at": NOW,
            "dry_run": True,
        }
        self.state = mock.patch.object(
            sup, "state", return_value={"MainPID": "123", "ActiveState": "active"}
        )
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.t.cleanup()

    def raw(self, **changes):
        value = dict(self.base)
        value.update(changes)
        return json.dumps(value).encode()

    def handle(self, **changes):
        return sup.handle(
            self.raw(**changes),
            caller_uid=os.getuid(),
            caller_pid=77,
            db_path=self.db,
            board="zer0-company",
            receipts=self.log,
            now=NOW,
        )

    def rejected(self, reason, **changes):
        with self.assertRaisesRegex(sup.Rejected, f"^{reason}$"):
            self.handle(**changes)

    def test_dry_run_writes_redacted_receipt_and_never_restarts(self):
        with mock.patch.object(sup.subprocess, "run") as run:
            result = self.handle()
        run.assert_not_called()
        self.assertEqual(result["detail"], "dry-run-authorized")
        self.assertNotIn("A" * 32, self.log.read_text())

    def test_build_task_allows_dry_run_but_blocks_execute(self):
        self.handle(task_id="t_db2e6a35", nonce="B" * 32)
        self.rejected("execute-not-authorized", task_id="t_db2e6a35", nonce="C" * 32, dry_run=False)

    def test_arbitrary_service_and_injection_rejected(self):
        self.rejected("wrong-service", service="ssh.service")
        self.rejected("wrong-service", service="hermes-gateway.service;id")

    def test_supervisor_self_restart_rejected(self):
        self.rejected("wrong-service", service="hermes-keel-gateway-restart-supervisor.service")

    def test_wrong_board_and_malformed_task(self):
        self.rejected("wrong-board", board="other")
        self.rejected("malformed-task-id", task_id="../t_235ade89")

    def test_stale_and_replayed_nonce(self):
        self.rejected("stale-request", created_at=NOW - 121)
        self.handle()
        self.rejected("replayed-nonce")

    def test_forged_missing_task(self):
        self.rejected("missing-or-ambiguous-task", task_id="t_deadbeef")

    def test_inactive_and_completed_tasks(self):
        db = sqlite3.connect(self.db)
        db.execute("update tasks set status='blocked' where id='t_235ade89'")
        db.commit()
        db.close()
        self.rejected("inactive-task")

    def test_unauthorized_text(self):
        db = sqlite3.connect(self.db)
        db.execute("update tasks set title='ordinary', body='nothing' where id='t_235ade89'")
        db.commit()
        db.close()
        self.rejected("restart-not-authorized")

    def test_symlink_db_and_receipt_rejected(self):
        link = self.root / "link.db"
        link.symlink_to(self.db)
        with self.assertRaisesRegex(sup.Rejected, "unsafe-board-db"):
            sup.authorize(link, "t_235ade89", dry_run=True)
        target = self.root / "target"
        target.write_text("")
        self.log.symlink_to(target)
        self.rejected("unsafe-receipt-log")

    def test_malformed_receipt_fails_closed(self):
        self.log.write_text("not-json\n")
        self.rejected("malformed-receipt")

    def test_exact_schema_rejects_arguments_and_environment(self):
        for field in ("command", "args", "env", "path"):
            value = dict(self.base)
            value[field] = "evil"
            with self.assertRaisesRegex(sup.Rejected, "malformed-fields"):
                sup.validate_request(json.dumps(value).encode(), board="zer0-company", now=NOW)

    def test_execute_uses_only_literal_argv(self):
        response = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(sup.subprocess, "run", return_value=response) as run:
            self.handle(dry_run=False)
        run.assert_called_once_with(
            ["systemctl", "--user", "restart", sup.SERVICE],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def test_concurrent_duplicate_has_one_success_under_server_serialization(self):
        self.handle()
        self.rejected("replayed-nonce")

    def test_duplicate_task_rows_impossible_by_primary_key_contract(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db = sqlite3.connect(self.db)
            db.execute(
                "insert into tasks values(?,?,?,?,?)",
                ("t_235ade89", "gateway restart", "hermes gateway", "running", None),
            )


if __name__ == "__main__":
    unittest.main()
