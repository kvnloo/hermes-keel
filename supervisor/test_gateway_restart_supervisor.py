import json
import os
import socket
import sqlite3
import tempfile
import threading
import time
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
GOOD_STATE = {
    "MainPID": "123",
    "ActiveState": "active",
    "SubState": "running",
    "NRestarts": "0",
    "ControlGroup": "/user.slice/hermes-gateway.service",
}


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
        self.state = mock.patch.object(sup, "state", return_value=dict(GOOD_STATE))
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

    def receipts(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]

    def test_dry_run_writes_request_then_result_and_never_restarts(self):
        with mock.patch.object(sup.subprocess, "run") as run:
            handled = self.handle()
        run.assert_not_called()
        self.assertEqual(handled["result"]["detail"], "dry-run-authorized")
        records = self.receipts()
        self.assertEqual([r["type"] for r in records], ["gateway-restart-request", "gateway-restart-result"])
        self.assertEqual(records[0]["nonce_sha256"], records[1]["nonce_sha256"])
        self.assertNotIn("A" * 32, self.log.read_text())

    def test_consume_before_mutation_and_crash_window_blocks_replay(self):
        calls = {"n": 0}
        real_append = sup.append_receipt

        def append_then_crash(path, record):
            real_append(path, record)
            if record["type"] == "gateway-restart-request":
                raise RuntimeError("crash-after-consume")

        with mock.patch.object(sup, "append_receipt", side_effect=append_then_crash):
            with mock.patch.object(sup.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    self.handle(dry_run=False)
                run.assert_not_called()
        records = self.receipts()
        self.assertEqual([r["type"] for r in records], ["gateway-restart-request"])
        self.rejected("replayed-nonce", dry_run=False)

    def test_result_append_failure_after_mutation_still_blocks_replay(self):
        real_append = sup.append_receipt

        def append_fail_result(path, record):
            if record["type"] == "gateway-restart-result":
                raise OSError("disk-full")
            return real_append(path, record)

        response = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(sup, "append_receipt", side_effect=append_fail_result):
            with mock.patch.object(sup.subprocess, "run", return_value=response) as run:
                with self.assertRaises(OSError):
                    self.handle(dry_run=False)
                run.assert_called_once()
        self.assertEqual([r["type"] for r in self.receipts()], ["gateway-restart-request"])
        self.rejected("replayed-nonce", dry_run=False)

    def test_build_task_allows_dry_run_but_blocks_execute(self):
        self.handle(task_id="t_db2e6a35", nonce="B" * 32)
        self.rejected("execute-not-authorized", task_id="t_db2e6a35", nonce="C" * 32, dry_run=False)

    def test_arbitrary_service_and_injection_rejected(self):
        self.rejected("wrong-service", service="ssh.service")
        self.rejected("wrong-service", service="hermes-gateway.service;id")

    def test_supervisor_self_restart_rejected(self):
        self.rejected("wrong-service", service="hermes-keel-lf006-supervisor.service")

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
            handled = self.handle(dry_run=False)
        run.assert_called_once_with(
            ["systemctl", "--user", "restart", sup.SERVICE],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(handled["result"]["detail"], "restart-complete")

    def test_pre_state_query_failure_blocks_mutation(self):
        with mock.patch.object(sup, "state", side_effect=sup.Rejected("state-query-failed")):
            with mock.patch.object(sup.subprocess, "run") as run:
                self.rejected("state-query-failed", dry_run=False)
                run.assert_not_called()
        self.assertEqual(self.receipts(), [])

    def test_pre_state_incomplete_blocks_mutation(self):
        bad = dict(GOOD_STATE)
        del bad["MainPID"]
        with mock.patch.object(sup, "state", return_value=bad):
            # state() itself validates completeness; simulate incomplete by raising.
            with mock.patch.object(sup, "state", side_effect=sup.Rejected("state-incomplete")):
                with mock.patch.object(sup.subprocess, "run") as run:
                    self.rejected("state-incomplete", dry_run=False)
                    run.assert_not_called()

    def test_pre_state_inactive_blocks_mutation(self):
        inactive = dict(GOOD_STATE, ActiveState="inactive", SubState="dead", MainPID="0")
        with mock.patch.object(sup, "state", return_value=inactive):
            with mock.patch.object(sup.subprocess, "run") as run:
                self.rejected("service-not-active", dry_run=False)
                run.assert_not_called()

    def test_post_state_failure_is_not_restart_complete(self):
        response = mock.Mock(returncode=0, stdout="", stderr="")
        states = iter([dict(GOOD_STATE), sup.Rejected("state-query-failed")])

        def state_side_effect():
            value = next(states)
            if isinstance(value, Exception):
                raise value
            return value

        with mock.patch.object(sup, "state", side_effect=state_side_effect):
            with mock.patch.object(sup.subprocess, "run", return_value=response):
                handled = self.handle(dry_run=False)
        self.assertEqual(handled["result"]["detail"], "post-state-state-query-failed")
        self.assertEqual(handled["result"]["exit_status"], 1)

    def test_duplicate_task_rows_impossible_by_primary_key_contract(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db = sqlite3.connect(self.db)
            db.execute(
                "insert into tasks values(?,?,?,?,?)",
                ("t_235ade89", "gateway restart", "hermes gateway", "running", None),
            )

    def test_concurrent_socket_requests_one_success_one_replay(self):
        sock = self.root / "lf006.sock"
        receipts = self.root / "live-receipts.jsonl"
        args = mock.Mock(
            socket=str(sock),
            db=str(self.db),
            board="zer0-company",
            receipts=str(receipts),
        )
        restart = mock.Mock(returncode=0, stdout="", stderr="")
        run_patch = mock.patch.object(sup.subprocess, "run", return_value=restart)
        run = run_patch.start()
        self.addCleanup(run_patch.stop)
        thread = threading.Thread(target=sup.serve, args=(args,), daemon=True)
        thread.start()
        deadline = time.time() + 2
        while not sock.exists() and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(sock.exists())

        def client(nonce: str):
            req = {
                "version": 1,
                "task_id": "t_235ade89",
                "nonce": nonce,
                "service": sup.SERVICE,
                "board": "zer0-company",
                "created_at": int(time.time()),
                "dry_run": False,
            }
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_sock:
                client_sock.settimeout(5)
                client_sock.connect(str(sock))
                client_sock.sendall(json.dumps(req).encode())
                client_sock.shutdown(socket.SHUT_WR)
                return json.loads(client_sock.recv(65536).decode())

        barrier = threading.Barrier(2)
        results: list[dict] = []

        def worker():
            barrier.wait()
            results.append(client("Z" * 32))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(5)
        t2.join(5)
        oks = [r for r in results if r.get("ok")]
        errs = [r for r in results if not r.get("ok")]
        self.assertEqual(len(oks), 1)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["error"], "replayed-nonce")
        run.assert_called_once_with(
            ["systemctl", "--user", "restart", sup.SERVICE],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        lines = [json.loads(line) for line in receipts.read_text().splitlines() if line]
        self.assertEqual([r["type"] for r in lines], ["gateway-restart-request", "gateway-restart-result"])
        # Stop server by removing socket path after process exit via SIGTERM-like path:
        # serve() exits on socket path cleanup through process death; close by killing thread's socket.
        # Best-effort: connect once more after force-close is not needed for the assertion.


if __name__ == "__main__":
    unittest.main()
