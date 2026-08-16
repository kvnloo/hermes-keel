#!/usr/bin/env python3
"""Narrow, fail-closed user gateway restart supervisor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import sqlite3
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

TASK_RE = re.compile(r"^t_[0-9a-f]{8}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
SERVICE = "hermes-gateway.service"
ACTIVE_STATUS = "running"
MAX_AGE = 120
MAX_REQUEST = 4096
RECEIPT_KEYS = {
    "type",
    "timestamp",
    "caller_uid",
    "caller_pid",
    "task_id",
    "nonce_sha256",
    "dry_run",
    "service",
    "pre",
    "post",
    "exit_status",
    "detail",
}
# Execute requires an active task whose body positively authorizes a live restart.
EXECUTE_MARKERS = (
    "captain explicitly authorized",
    "explicitly authorized restarting",
    "authorized restarting the",
    "perform the actual gateway restart",
)
EXECUTE_DENY = (
    "do not perform the actual gateway restart",
    "supervisor only",
    "dry-run only",
    "establishes the supervisor only",
)


class Rejected(Exception):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def state() -> dict[str, Any]:
    cp = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            SERVICE,
            "--property=MainPID,ActiveState,SubState,NRestarts,ControlGroup",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    values: dict[str, Any] = {"query_exit": cp.returncode}
    for line in cp.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def validate_request(raw: bytes, *, board: str, now: int) -> dict[str, Any]:
    try:
        req = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected("malformed-json") from exc
    expected = {"version", "task_id", "nonce", "service", "board", "created_at", "dry_run"}
    if not isinstance(req, dict) or set(req) != expected:
        raise Rejected("malformed-fields")
    if req["version"] != 1 or type(req["dry_run"]) is not bool or type(req["created_at"]) is not int:
        raise Rejected("malformed-types")
    if not isinstance(req["task_id"], str) or not TASK_RE.fullmatch(req["task_id"]):
        raise Rejected("malformed-task-id")
    if not isinstance(req["nonce"], str) or not NONCE_RE.fullmatch(req["nonce"]):
        raise Rejected("malformed-nonce")
    if req["service"] != SERVICE:
        raise Rejected("wrong-service")
    if req["board"] != board:
        raise Rejected("wrong-board")
    if abs(now - req["created_at"]) > MAX_AGE:
        raise Rejected("stale-request")
    return req


def authorize(db_path: Path, task_id: str, *, dry_run: bool) -> None:
    if db_path.is_symlink() or not db_path.is_file():
        raise Rejected("unsafe-board-db")
    # mode=ro still needs the board directory writable for SQLite WAL -shm
    # coordination. The unit grants only that board path; this process only SELECTs.
    uri = f"file:{db_path}?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT title, body, status, completed_at FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchall()
        db.close()
    except sqlite3.Error as exc:
        raise Rejected("board-read-failed") from exc
    if len(rows) != 1:
        raise Rejected("missing-or-ambiguous-task")
    title, body, status, completed_at = rows[0]
    text = f"{title or ''}\n{body or ''}".lower()
    if status != ACTIVE_STATUS or completed_at is not None:
        raise Rejected("inactive-task")
    if "gateway restart" not in text and not re.search(r"restart.{0,80}gateway", text, re.DOTALL):
        raise Rejected("restart-not-authorized")
    if SERVICE not in text and "hermes gateway" not in text and "telegram gateway" not in text:
        raise Rejected("service-not-authorized")
    if not dry_run:
        if any(marker in text for marker in EXECUTE_DENY):
            raise Rejected("execute-not-authorized")
        if not any(marker in text for marker in EXECUTE_MARKERS):
            raise Rejected("execute-not-authorized")


def load_nonces(receipts: Path) -> set[str]:
    used: set[str] = set()
    if not receipts.exists():
        return used
    if receipts.is_symlink() or not receipts.is_file():
        raise Rejected("unsafe-receipt-log")
    with receipts.open("rb") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise Rejected("malformed-receipt") from exc
            if not isinstance(record, dict) or set(record) != RECEIPT_KEYS:
                raise Rejected("malformed-receipt")
            used.add(record["nonce_sha256"])
    return used


def append_receipt(receipts: Path, record: dict[str, Any]) -> None:
    receipts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(receipts, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, canonical_json(record) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def handle(
    raw: bytes,
    *,
    caller_uid: int,
    caller_pid: int,
    db_path: Path,
    board: str,
    receipts: Path,
    now: int | None = None,
) -> dict[str, Any]:
    now = int(time.time()) if now is None else now
    req = validate_request(raw, board=board, now=now)
    nonce_hash = hashlib.sha256(req["nonce"].encode()).hexdigest()
    used = load_nonces(receipts)
    if nonce_hash in used:
        raise Rejected("replayed-nonce")
    authorize(db_path, req["task_id"], dry_run=req["dry_run"])
    pre = state()
    status = 0
    detail = "dry-run-authorized"
    if not req["dry_run"]:
        try:
            cp = subprocess.run(
                ["systemctl", "--user", "restart", SERVICE],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            status = cp.returncode
            detail = "restart-complete" if status == 0 else "restart-failed"
        except subprocess.TimeoutExpired:
            status, detail = 124, "restart-timeout"
    post = state()
    record = {
        "type": "gateway-restart-result",
        "timestamp": int(time.time()),
        "caller_uid": caller_uid,
        "caller_pid": caller_pid,
        "task_id": req["task_id"],
        "nonce_sha256": nonce_hash,
        "dry_run": req["dry_run"],
        "service": SERVICE,
        "pre": pre,
        "post": post,
        "exit_status": status,
        "detail": detail,
    }
    append_receipt(receipts, record)
    return record


def serve(args: argparse.Namespace) -> None:
    sock_path = Path(args.socket)
    if sock_path.exists() or sock_path.is_symlink():
        raise SystemExit("socket path already exists")
    sock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    server.listen(8)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                pid, uid, _gid = struct.unpack(
                    "3i",
                    conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")),
                )
                try:
                    raw = conn.recv(MAX_REQUEST + 1)
                    if len(raw) > MAX_REQUEST:
                        raise Rejected("request-too-large")
                    result = {
                        "ok": True,
                        "receipt": handle(
                            raw,
                            caller_uid=uid,
                            caller_pid=pid,
                            db_path=Path(args.db),
                            board=args.board,
                            receipts=Path(args.receipts),
                        ),
                    }
                except Rejected as exc:
                    result = {"ok": False, "error": str(exc)}
                except Exception:
                    result = {"ok": False, "error": "internal-failure"}
                conn.sendall(canonical_json(result) + b"\n")
    finally:
        server.close()
        sock_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--board", required=True)
    parser.add_argument("--receipts", required=True)
    serve(parser.parse_args())


if __name__ == "__main__":
    main()
