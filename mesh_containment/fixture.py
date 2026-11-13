#!/usr/bin/env python3
"""Local-only model of competing Mesh :8787 owners.

The fixture deliberately has no socket implementation.  ``requested_port`` is
part of the signed transport identity, while all effects are confined to its
receipt directory.  The canonical board is opened read-only and is never a
receipt or lock target.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

PORT = 8787
MAX_AGE_SECONDS = 120
KINDS = {"task", "run", "event"}
EVENTS = {"progress", "completion-requested"}
EXACT_FIELDS = {
    "version", "kind", "task_id", "run_id", "revision", "board_path",
    "issued_at", "payload", "signature",
}


class ContainmentError(Exception):
    """A fail-closed fixture verdict."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sign_envelope(envelope: dict[str, Any], key: bytes) -> dict[str, Any]:
    unsigned = dict(envelope)
    unsigned.pop("signature", None)
    result = dict(unsigned)
    result["signature"] = hmac.new(key, canonical_json(unsigned), hashlib.sha256).hexdigest()
    return result


def _safe_regular(path: Path, *, may_not_exist: bool = False) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ContainmentError("unsafe-path")
    if not may_not_exist and not path.is_file():
        raise ContainmentError("missing-path")


class DisposableMeshListener:
    """A reversible listener owner with durable receipt idempotency."""

    def __init__(self, *, owner: str, board: Path, root: Path, key: bytes, now: int | None = None):
        if not owner or not key:
            raise ValueError("owner and key are required")
        self.owner = owner
        self.board = board.resolve(strict=True)
        self.root = root
        self.key = key
        self.now = int(time.time()) if now is None else now
        self.requested_port = PORT
        self._owner_fd: int | None = None

    def start(self) -> None:
        _safe_regular(self.board)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        owner_lock = self.root / "port-8787.owner.lock"
        if owner_lock.is_symlink():
            raise ContainmentError("unsafe-owner-lock")
        fd = os.open(owner_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise ContainmentError("second-listener") from exc
        os.ftruncate(fd, 0)
        os.write(fd, self.owner.encode())
        os.fsync(fd)
        self._owner_fd = fd

    def stop(self) -> None:
        if self._owner_fd is not None:
            fcntl.flock(self._owner_fd, fcntl.LOCK_UN)
            os.close(self._owner_fd)
            self._owner_fd = None

    def __enter__(self) -> "DisposableMeshListener":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _validate(self, envelope: dict[str, Any]) -> None:
        if not isinstance(envelope, dict) or set(envelope) != EXACT_FIELDS:
            raise ContainmentError("malformed-envelope")
        if envelope["version"] != 1 or envelope["kind"] not in KINDS:
            raise ContainmentError("malformed-envelope")
        unsigned = dict(envelope)
        signature = unsigned.pop("signature")
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, hmac.new(self.key, canonical_json(unsigned), hashlib.sha256).hexdigest()
        ):
            raise ContainmentError("bad-signature")
        if not isinstance(envelope["board_path"], str):
            raise ContainmentError("malformed-envelope")
        # Require the signed canonical spelling too: a symlink alias must not
        # select the board merely because it resolves to the same inode.
        if Path(envelope["board_path"]).absolute() != self.board:
            raise ContainmentError("forged-board-path")
        if type(envelope["issued_at"]) is not int or abs(self.now - envelope["issued_at"]) > MAX_AGE_SECONDS:
            raise ContainmentError("stale-envelope")
        if type(envelope["revision"]) is not int or envelope["revision"] < 1:
            raise ContainmentError("malformed-envelope")
        if not isinstance(envelope["task_id"], str) or type(envelope["run_id"]) is not int:
            raise ContainmentError("malformed-envelope")
        if not isinstance(envelope["payload"], dict):
            raise ContainmentError("malformed-envelope")

    def _authorize(self, envelope: dict[str, Any]) -> None:
        try:
            db = sqlite3.connect(f"file:{self.board}?mode=ro", uri=True)
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT t.status, t.completed_at, r.status FROM tasks t "
                "JOIN runs r ON r.task_id=t.id WHERE t.id=? AND r.id=?",
                (envelope["task_id"], envelope["run_id"]),
            ).fetchone()
            db.close()
        except sqlite3.Error as exc:
            raise ContainmentError("board-read-failed") from exc
        if row is None:
            raise ContainmentError("unknown-task-run")
        task_status, completed_at, run_status = row
        if completed_at is not None or task_status != "running" or run_status != "running":
            raise ContainmentError("stale-run")
        payload = envelope["payload"]
        forbidden = {"create", "claim", "complete", "accept", "approve", "acceptance"}
        if forbidden.intersection(payload) or payload.get("action") in forbidden:
            raise ContainmentError("canonical-authority-forbidden")
        if envelope["kind"] == "event" and payload.get("event") not in EVENTS:
            raise ContainmentError("event-forbidden")

    def transport(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if self._owner_fd is None:
            raise ContainmentError("listener-not-started")
        self._validate(envelope)
        self._authorize(envelope)
        unsigned = dict(envelope)
        unsigned.pop("signature")
        source_hash = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        idem = f'{envelope["kind"]}:{envelope["task_id"]}:{envelope["run_id"]}:{envelope["revision"]}'
        receipt = {
            "type": "mesh-transport-received", "owner": self.owner,
            "requested_port": PORT, "idempotency_key": idem, "source_hash": source_hash,
        }
        lock_path = self.root / "receipts.lock"
        receipt_path = self.root / "receipts.jsonl"
        if lock_path.is_symlink() or receipt_path.is_symlink():
            raise ContainmentError("unsafe-receipt-path")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            existing: dict[str, str] = {}
            if receipt_path.exists():
                _safe_regular(receipt_path)
                for line in receipt_path.read_bytes().splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ContainmentError("malformed-receipt") from exc
                    if set(record) != set(receipt):
                        raise ContainmentError("malformed-receipt")
                    previous = existing.setdefault(record["idempotency_key"], record["source_hash"])
                    if previous != record["source_hash"]:
                        raise ContainmentError("receipt-conflict")
            if idem in existing:
                if existing[idem] != source_hash:
                    raise ContainmentError("receipt-conflict")
                return {"status": "duplicate", "receipt": receipt}
            fd = os.open(receipt_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, canonical_json(receipt) + b"\n")
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        result = {"status": "transported", "receipt": receipt}
        if envelope["kind"] == "event" and envelope["payload"].get("event") == "completion-requested":
            result["handoff"] = {
                "authority": "canonical-kanban", "operation": "complete",
                "task_id": envelope["task_id"], "run_id": envelope["run_id"],
            }
        return result
