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
import threading
import time
from pathlib import Path
from typing import Any

TASK_RE = re.compile(r"^t_[0-9a-f]{8}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
SERVICE = "hermes-gateway.service"
ACTIVE_STATUS = "running"
MAX_AGE = 120
MAX_REQUEST = 4096
STATE_REQUIRED = ("MainPID", "ActiveState", "SubState", "NRestarts", "ControlGroup")
REQUEST_RECEIPT_KEYS = {
    "type",
    "timestamp",
    "caller_uid",
    "caller_pid",
    "task_id",
    "nonce_sha256",
    "dry_run",
    "service",
    "pre",
}
RESULT_RECEIPT_KEYS = {
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
RECEIPT_TYPES = {
    "gateway-restart-request": REQUEST_RECEIPT_KEYS,
    "gateway-restart-result": RESULT_RECEIPT_KEYS,
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
    try:
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
    except subprocess.TimeoutExpired as exc:
        raise Rejected("state-query-timeout") from exc
    if cp.returncode != 0:
        raise Rejected("state-query-failed")
    values: dict[str, Any] = {}
    for line in cp.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    for key in STATE_REQUIRED:
        if key not in values or values[key] == "":
            raise Rejected("state-incomplete")
    return values


def require_pre_state(pre: dict[str, Any]) -> None:
    if pre.get("ActiveState") != "active" or pre.get("SubState") != "running":
        raise Rejected("service-not-active")
    if not str(pre.get("MainPID", "0")).isdigit() or int(pre["MainPID"]) <= 0:
        raise Rejected("service-not-active")


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
            if not isinstance(record, dict) or "type" not in record:
                raise Rejected("malformed-receipt")
            expected = RECEIPT_TYPES.get(record["type"])
            if expected is None or set(record) != expected:
                raise Rejected("malformed-receipt")
            # Either a request-consume or a result permanently spends the nonce.
            used.add(record["nonce_sha256"])
    return used


def append_receipt(receipts: Path, record: dict[str, Any]) -> None:
    receipts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(receipts, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        payload = canonical_json(record) + b"\n"
        written = 0
        while written < len(payload):
            count = os.write(fd, payload[written:])
            if count <= 0:
                raise OSError("short receipt write")
            written += count
        os.fsync(fd)
    finally:
        os.close(fd)


def classify_result(*, dry_run: bool, restart_exit: int | None, post: dict[str, Any] | None, post_error: str | None) -> tuple[int, str]:
    if dry_run:
        return 0, "dry-run-authorized"
    if post_error is not None:
        return 1, f"post-state-{post_error}"
    if restart_exit is None:
        return 1, "restart-not-attempted"
    if restart_exit != 0:
        return restart_exit, "restart-failed"
    if post is None:
        return 1, "post-state-missing"
    if post.get("ActiveState") != "active" or post.get("SubState") != "running":
        return 1, "post-state-not-active"
    if not str(post.get("MainPID", "0")).isdigit() or int(post["MainPID"]) <= 0:
        return 1, "post-state-not-active"
    return 0, "restart-complete"


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
    require_pre_state(pre)

    # Atomic consume: durable request receipt is fsynced before any mutation.
    request_record = {
        "type": "gateway-restart-request",
        "timestamp": int(time.time()),
        "caller_uid": caller_uid,
        "caller_pid": caller_pid,
        "task_id": req["task_id"],
        "nonce_sha256": nonce_hash,
        "dry_run": req["dry_run"],
        "service": SERVICE,
        "pre": pre,
    }
    append_receipt(receipts, request_record)

    restart_exit: int | None = None
    post: dict[str, Any] | None = None
    post_error: str | None = None
    if not req["dry_run"]:
        try:
            cp = subprocess.run(
                ["systemctl", "--user", "restart", SERVICE],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            restart_exit = cp.returncode
        except subprocess.TimeoutExpired:
            restart_exit = 124
    try:
        post = state()
    except Rejected as exc:
        post_error = str(exc)

    exit_status, detail = classify_result(
        dry_run=req["dry_run"],
        restart_exit=restart_exit,
        post=post,
        post_error=post_error,
    )
    result_record = {
        "type": "gateway-restart-result",
        "timestamp": int(time.time()),
        "caller_uid": caller_uid,
        "caller_pid": caller_pid,
        "task_id": req["task_id"],
        "nonce_sha256": nonce_hash,
        "dry_run": req["dry_run"],
        "service": SERVICE,
        "pre": pre,
        "post": post if post is not None else {"error": post_error or "missing"},
        "exit_status": exit_status,
        "detail": detail,
    }
    append_receipt(receipts, result_record)
    return {"request": request_record, "result": result_record}


def serve(args: argparse.Namespace) -> None:
    sock_path = Path(args.socket)
    if sock_path.exists() or sock_path.is_symlink():
        raise SystemExit("socket path already exists")
    sock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    server.listen(8)
    # signal handlers are only valid in the main thread (production path).
    if threading.current_thread() is threading.main_thread():
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
                    handled = handle(
                        raw,
                        caller_uid=uid,
                        caller_pid=pid,
                        db_path=Path(args.db),
                        board=args.board,
                        receipts=Path(args.receipts),
                    )
                    result = {"ok": True, "receipt": handled["result"], "request": handled["request"]}
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
