from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from mesh_containment.fixture import ContainmentError, DisposableMeshListener, sign_envelope

NOW = 1_787_070_000
KEY = b"disposable-fixture-key"


class MeshContainmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.board = self.root / "canonical.db"
        db = sqlite3.connect(self.board)
        db.executescript(
            "CREATE TABLE tasks(id TEXT PRIMARY KEY,status TEXT,completed_at INTEGER);"
            "CREATE TABLE runs(id INTEGER PRIMARY KEY,task_id TEXT,status TEXT);"
            "CREATE TABLE keel_acceptance(id TEXT PRIMARY KEY,claim TEXT);"
            "INSERT INTO tasks VALUES('t_1234abcd','running',NULL);"
            "INSERT INTO runs VALUES(41,'t_1234abcd','running');"
            "INSERT INTO keel_acceptance VALUES('sentinel','SEALED-NOT-ACCEPTED');"
        )
        db.commit()
        db.close()
        self.before_bytes = self.board.read_bytes()
        self.before_logical = self.logical_identity()
        self.receipts = self.root / "disposable"
        self.listener = DisposableMeshListener(
            owner="linux-owner", board=self.board, root=self.receipts, key=KEY, now=NOW
        )
        self.listener.start()

    def tearDown(self) -> None:
        self.listener.stop()
        self.assertEqual(hashlib.sha256(self.board.read_bytes()).digest(), hashlib.sha256(self.before_bytes).digest())
        self.assertEqual(self.logical_identity(), self.before_logical)
        self.temp.cleanup()

    def logical_identity(self):
        db = sqlite3.connect(self.board)
        result = tuple(db.iterdump())
        db.close()
        return result

    def envelope(self, *, kind="event", revision=1, issued_at=NOW, payload=None, board=None, run_id=41):
        return sign_envelope(
            {
                "version": 1,
                "kind": kind,
                "task_id": "t_1234abcd",
                "run_id": run_id,
                "revision": revision,
                "board_path": str(board or self.board),
                "issued_at": issued_at,
                "payload": payload if payload is not None else {"event": "progress", "percent": 50},
            },
            KEY,
        )

    def rejected(self, reason, **changes):
        envelope = self.envelope(**changes)
        with self.assertRaisesRegex(ContainmentError, f"^{reason}$"):
            self.listener.transport(envelope)

    def test_signed_task_run_event_transport_only(self):
        for revision, kind in enumerate(("task", "run", "event"), 1):
            payload = {"event": "progress"} if kind == "event" else {"description": kind}
            result = self.listener.transport(self.envelope(kind=kind, revision=revision, payload=payload))
            self.assertEqual(result["status"], "transported")
            self.assertNotIn("handoff", result)
        self.assertEqual(len((self.receipts / "receipts.jsonl").read_text().splitlines()), 3)

    def test_completion_is_handoff_not_canonical_mutation(self):
        result = self.listener.transport(self.envelope(payload={"event": "completion-requested"}))
        self.assertEqual(
            result["handoff"],
            {"authority": "canonical-kanban", "operation": "complete", "task_id": "t_1234abcd", "run_id": 41},
        )
        self.assertEqual(self.logical_identity(), self.before_logical)

    def test_red_direct_create_claim_complete_and_acceptance(self):
        for revision, action in enumerate(("create", "claim", "complete", "accept", "approve"), 1):
            self.rejected(
                "canonical-authority-forbidden", revision=revision,
                payload={"event": "progress", "action": action},
            )
        self.rejected(
            "canonical-authority-forbidden", revision=10,
            payload={"event": "progress", "acceptance": {"claim": True}},
        )
        self.assertFalse((self.receipts / "receipts.jsonl").exists())

    def test_red_forged_board_path(self):
        forged = self.root / "forged.db"
        forged.write_bytes(self.board.read_bytes())
        self.rejected("forged-board-path", board=forged)
        alias = self.root / "canonical-alias.db"
        alias.symlink_to(self.board)
        self.rejected("forged-board-path", board=alias)

    def test_receipt_replay_idempotent_and_conflict_fails_closed(self):
        envelope = self.envelope()
        self.assertEqual(self.listener.transport(envelope)["status"], "transported")
        self.assertEqual(self.listener.transport(envelope)["status"], "duplicate")
        conflict = self.envelope(payload={"event": "progress", "percent": 99})
        with self.assertRaisesRegex(ContainmentError, "^receipt-conflict$"):
            self.listener.transport(conflict)
        self.assertEqual(len((self.receipts / "receipts.jsonl").read_text().splitlines()), 1)

    def test_receipt_lock_serializes_concurrent_replay(self):
        envelope = self.envelope()
        results = []
        errors = []
        barrier = threading.Barrier(12)

        def send():
            try:
                barrier.wait()
                results.append(self.listener.transport(envelope)["status"])
            except Exception as exc:  # surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=send) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(results.count("transported"), 1)
        self.assertEqual(results.count("duplicate"), 11)
        self.assertEqual(len((self.receipts / "receipts.jsonl").read_text().splitlines()), 1)

    def test_restart_preserves_idempotency(self):
        envelope = self.envelope()
        self.listener.transport(envelope)
        self.listener.stop()
        self.listener = DisposableMeshListener(
            owner="replacement-owner", board=self.board, root=self.receipts, key=KEY, now=NOW
        )
        self.listener.start()
        self.assertEqual(self.listener.transport(envelope)["status"], "duplicate")

    def test_red_stale_envelope_and_stale_run(self):
        self.rejected("stale-envelope", issued_at=NOW - 121)
        db = sqlite3.connect(self.board)
        db.execute("UPDATE runs SET status='done' WHERE id=41")
        db.commit()
        db.close()
        changed_bytes = self.board.read_bytes()
        changed_logical = self.logical_identity()
        try:
            self.rejected("stale-run")
        finally:
            # This test's canonical setup mutation is outside Mesh and is restored exactly.
            self.board.write_bytes(self.before_bytes)
        self.assertNotEqual(hashlib.sha256(changed_bytes).digest(), hashlib.sha256(self.before_bytes).digest())
        self.assertNotEqual(changed_logical, self.before_logical)

    def test_red_bad_signature(self):
        envelope = self.envelope()
        envelope["signature"] = "0" * 64
        with self.assertRaisesRegex(ContainmentError, "^bad-signature$"):
            self.listener.transport(envelope)

    def test_red_second_competing_8787_listener(self):
        rival = DisposableMeshListener(owner="mbp-owner", board=self.board, root=self.receipts, key=KEY, now=NOW)
        self.assertEqual(rival.requested_port, 8787)
        with self.assertRaisesRegex(ContainmentError, "^second-listener$"):
            rival.start()
        self.listener.stop()
        rival.start()
        try:
            self.assertEqual(rival.requested_port, 8787)
            self.assertEqual(rival.transport(self.envelope())["status"], "transported")
        finally:
            rival.stop()
        self.listener = DisposableMeshListener(
            owner="linux-owner-restored", board=self.board, root=self.receipts, key=KEY, now=NOW
        )
        self.listener.start()


if __name__ == "__main__":
    unittest.main()
