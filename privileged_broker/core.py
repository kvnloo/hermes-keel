#!/usr/bin/env python3
"""Captain-gated fixed-action privileged broker (stdlib only)."""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import stat
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

ACTION = "ollama-system-runtime-switch-v2"
HOST = "groot"
SERVICE = "ollama.service"
PORT = 11434
OLD_BINARY = "/usr/bin/ollama"
OLD_SHA256 = "ab27361e1e4c70a5aed215cce0cf6033bbf61650a0eb7e4b63cf01c76a06353a"
OLD_VERSION = "0.16.1"
NEW_SHA256 = "d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4"
NEW_BINARY = f"/usr/local/lib/hermes-privileged-broker/runtimes/sha256-{NEW_SHA256}/ollama"
NEW_VERSION = "0.32.14"
MODEL_STORE = "/mnt/zer0models/zer0-models/ollama"
MODEL_NAME = "qwen2.5:3b"
BOARD_DB = Path("/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db")
DROPIN = "/etc/systemd/system/ollama.service.d/10-hermes-cuda-runtime.conf"
DROPIN_BYTES = ("[Service]\nExecStart=\nExecStart=" + NEW_BINARY + " serve\n"
                "Environment=OLLAMA_HOST=127.0.0.1:11434\n"
                "Environment=OLLAMA_MODELS=" + MODEL_STORE + "\n").encode()
SCHEMA = {"version", "operation_id", "action", "target_host", "requester_task", "requester_run",
          "nonce", "created_at", "expires_at", "expected_pre_state", "sealed_package",
          "fixed_operation", "rollback"}
PRE_STATE_KEYS = {"service", "active", "fragment", "fragment_sha256", "dropins", "exec_start",
                  "environment", "main_pid", "process_executable", "process_sha256", "version",
                  "daemon_pids", "listeners", "model_store", "model_store_manifest_sha256",
                  "board_identity"}
IDENTITY_KEYS = {"path", "uid", "gid", "mode", "device", "inode", "sha256", "schema_sha256"}
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
PHASES = {"prepared", "consumed", "mutation_started", "health_passed", "committed",
          "rollback_started", "rollback_verified", "recovery_required", "preflight_rejected"}


class Rejected(Exception):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _safe_regular(path: Path, allowed_uids: tuple[int, ...] = (0,)) -> tuple[int, os.stat_result]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid not in allowed_uids:
        os.close(fd)
        raise Rejected("unsafe-file")
    return fd, st


def file_hash(path: Path, allowed_uids: tuple[int, ...] = (0,)) -> str:
    fd, _ = _safe_regular(path, allowed_uids)
    h = hashlib.sha256()
    try:
        while chunk := os.read(fd, 1024 * 1024):
            h.update(chunk)
    finally:
        os.close(fd)
    return h.hexdigest()


def file_identity(path: Path, allowed_uids: tuple[int, ...] = (0,)) -> dict[str, Any]:
    fd, _ = _safe_regular(path, allowed_uids)
    try:
        db = sqlite3.connect(f"file:/proc/self/fd/{fd}?mode=ro", uri=True)
        try:
            return _identity_from_fd(fd, db)
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise Rejected("invalid-board-schema") from exc
    finally:
        os.close(fd)


def _identity_from_fd(fd: int, db: sqlite3.Connection) -> dict[str, Any]:
    """Measure file and schema through the descriptor backing ``db``."""
    st = os.fstat(fd)
    h = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        h.update(chunk)
    rows = db.execute("select type,name,tbl_name,sql from sqlite_master order by type,name").fetchall()
    opened_path = os.readlink(f"/proc/self/fd/{fd}")
    if opened_path.endswith(" (deleted)"):
        opened_path = opened_path[:-10]
    return {"path": opened_path, "uid": st.st_uid, "gid": st.st_gid,
            "mode": stat.S_IMODE(st.st_mode), "device": st.st_dev, "inode": st.st_ino,
            "sha256": h.hexdigest(), "schema_sha256": digest(rows)}


def canonical_pre_state(runtime: dict[str, Any], board_path: Path,
                        allowed_uids: tuple[int, ...] = (0,)) -> dict[str, Any]:
    state = dict(runtime)
    state["board_identity"] = file_identity(board_path, allowed_uids)
    if set(state) != PRE_STATE_KEYS:
        raise Rejected("bad-canonical-pre-state")
    return state


def tree_manifest_hash(root: Path) -> str:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise Rejected("unsafe-model-store")
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Rejected("model-store-symlink")
        if path.is_file():
            rows.append([str(path.relative_to(root)), path.stat().st_size, file_hash(path, (0, os.getuid()))])
    if not rows:
        raise Rejected("empty-model-store")
    return digest(rows)


def fixed_operation() -> dict[str, Any]:
    return {"executable": NEW_BINARY, "argv": [NEW_BINARY, "serve"], "executable_sha256": NEW_SHA256,
            "dropin": DROPIN, "dropin_sha256": hashlib.sha256(DROPIN_BYTES).hexdigest(),
            "model_store": MODEL_STORE, "listen": "127.0.0.1:11434", "service": SERVICE,
            "health": {"url": "http://127.0.0.1:11434/api/version", "version": NEW_VERSION,
                       "processes": 1, "cuda_required": True},
            "smoke": {"model": MODEL_NAME, "minimum_eval_tokens_per_second": 100.0,
                      "prompt": "Reply exactly OK", "response": "OK"}}


def rollback() -> dict[str, Any]:
    return {"remove_dropin": DROPIN, "restore_executable": OLD_BINARY,
            "restore_sha256": OLD_SHA256, "restore_version": OLD_VERSION,
            "daemon_reload": True, "restart": SERVICE, "verify_pre_state_byte_exact": True}


def fixture_pre_state() -> dict[str, Any]:
    """Complete-shaped deterministic fixture; production create-request captures live state."""
    return {"service": SERVICE, "active": True, "fragment": "/usr/lib/systemd/system/ollama.service",
            "fragment_sha256": "0" * 64, "dropins": [], "exec_start": [OLD_BINARY, "serve"],
            "environment": {"OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_MODELS": MODEL_STORE},
            "main_pid": 4242, "process_executable": OLD_BINARY, "process_sha256": OLD_SHA256,
            "version": OLD_VERSION, "daemon_pids": [4242],
            "listeners": [{"address": "127.0.0.1", "port": PORT, "pid": 4242}],
            "model_store": MODEL_STORE, "model_store_manifest_sha256": "1" * 64,
            "board_identity": {"path": "/fixture/kanban.db", "uid": 0, "gid": 0,
                               "mode": 0o600, "device": 1, "inode": 1, "sha256": "3" * 64,
                               "schema_sha256": "4" * 64}}


def sealed_package(path: str, manifest_sha256: str) -> dict[str, Any]:
    return {"path": path, "manifest_sha256": manifest_sha256,
            "runtime_member": "runtime/ollama", "runtime_sha256": NEW_SHA256,
            "installed_executable": NEW_BINARY}


def make_request(task: str, run: int, nonce: str, now: int, ttl: int = 1800,
                 pre_state: dict[str, Any] | None = None,
                 package: dict[str, Any] | None = None) -> dict[str, Any]:
    req = {"version": 2, "operation_id": f"{ACTION}:{task}:{run}:{nonce}", "action": ACTION,
           "target_host": HOST, "requester_task": task, "requester_run": run, "nonce": nonce,
           "created_at": now, "expires_at": now + ttl,
           "expected_pre_state": pre_state if pre_state is not None else fixture_pre_state(),
           "sealed_package": package if package is not None else sealed_package(
               "/fixture/package", "2" * 64),
           "fixed_operation": fixed_operation(), "rollback": rollback()}
    validate_request(req, now=now)
    return req


def validate_request(req: Any, *, now: int | None = None) -> None:
    now = int(time.time()) if now is None else now
    if not isinstance(req, dict) or set(req) != SCHEMA or req.get("version") != 2:
        raise Rejected("bad-schema")
    if req["action"] != ACTION or req["target_host"] != HOST:
        raise Rejected("wrong-action-or-host")
    if req["fixed_operation"] != fixed_operation() or req["rollback"] != rollback():
        raise Rejected("operation-not-fixed")
    package = req["sealed_package"]
    if (not isinstance(package, dict) or package != sealed_package(
            package.get("path", "") if isinstance(package, dict) else "",
            package.get("manifest_sha256", "") if isinstance(package, dict) else "") or
            not str(package["path"]).startswith("/") or
            len(package["manifest_sha256"]) != 64 or
            any(c not in "0123456789abcdef" for c in package["manifest_sha256"])):
        raise Rejected("bad-sealed-package")
    pre = req["expected_pre_state"]
    if not isinstance(pre, dict) or set(pre) != PRE_STATE_KEYS or pre["service"] != SERVICE:
        raise Rejected("bad-pre-state")
    if pre["process_executable"] != OLD_BINARY or pre["process_sha256"] != OLD_SHA256 or pre["version"] != OLD_VERSION:
        raise Rejected("wrong-rollback-target")
    if pre["model_store"] != MODEL_STORE or not all(isinstance(pre[x], str) and len(pre[x]) == 64 for x in ("fragment_sha256", "model_store_manifest_sha256")):
        raise Rejected("bad-pre-state-hash")
    board = pre["board_identity"]
    if (not isinstance(board, dict) or set(board) != IDENTITY_KEYS or
            board["path"] == "" or not str(board["path"]).startswith("/") or
            any(type(board[x]) is not int or board[x] < 0 for x in ("uid", "gid", "mode", "device", "inode")) or
            any(not isinstance(board[x], str) or len(board[x]) != 64
                for x in ("sha256", "schema_sha256"))):
        raise Rejected("bad-board-identity")
    if type(req["requester_run"]) is not int or not str(req["requester_task"]).startswith("t_"):
        raise Rejected("bad-task-run")
    if not isinstance(req["nonce"], str) or len(req["nonce"]) < 32:
        raise Rejected("bad-nonce")
    if type(req["created_at"]) is not int or type(req["expires_at"]) is not int:
        raise Rejected("bad-time")
    if req["expires_at"] <= now or req["expires_at"] - req["created_at"] > 3600:
        raise Rejected("expired")


def _open_bound_board(db_path: Path, req: dict[str, Any], request_hash: str, *,
                      writable: bool) -> tuple[sqlite3.Connection, dict[str, Any]]:
    """Open once without following symlinks, then verify/query that connection."""
    flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(db_path, flags)
    except OSError as exc:
        raise Rejected("unsafe-board") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid not in (0, os.getuid()):
            raise Rejected("unsafe-board")
        mode = "rw" if writable else "ro"
        db = sqlite3.connect(f"file:/proc/self/fd/{fd}?mode={mode}", uri=True,
                             timeout=0, isolation_level=None)
        try:
            actual = _identity_from_fd(fd, db)
            expected = req["expected_pre_state"]["board_identity"]
            if expected["path"] != "/fixture/kanban.db":
                for key in ("path", "uid", "gid", "mode", "device", "inode", "schema_sha256"):
                    if actual[key] != expected[key]:
                        raise Rejected("authoritative-board-drift")
            if writable:
                db.execute("pragma busy_timeout=0")
                db.execute("begin immediate")
                fenced = _identity_from_fd(fd, db)
                if any(fenced[key] != actual[key] for key in ("device", "inode", "schema_sha256")):
                    raise Rejected("authoritative-board-drift")
                actual = fenced
            else:
                db.execute("pragma query_only=on")
            _task_active_connection(db, req["requester_task"], req["requester_run"], request_hash)
            return db, actual
        except Exception:
            db.close()
            raise
    except sqlite3.Error as exc:
        raise Rejected("canonical-mutation-fence-unavailable" if writable else "unsafe-board") from exc
    finally:
        os.close(fd)


def task_active(db_path: Path, task: str, run: int, request_hash: str) -> None:
    """Compatibility query helper; ceremony paths use _open_bound_board."""
    if db_path.is_symlink() or not db_path.is_file():
        raise Rejected("unsafe-board")
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        _task_active_connection(db, task, run, request_hash)
    finally:
        db.close()


def validate_board_authority(db_path: Path, req: dict[str, Any], request_hash: str) -> None:
    db, _ = _open_bound_board(db_path, req, request_hash, writable=False)
    db.close()


def _task_active_connection(db: sqlite3.Connection, task: str, run: int,
                            request_hash: str) -> None:
    """Validate authority inside the transaction that fences canonical writers."""
    task_columns = {column[1] for column in db.execute("pragma table_info(tasks)")}
    run_columns = {column[1] for column in db.execute("pragma table_info(task_runs)")}
    extended = {"block_kind", "current_run_id"}.issubset(task_columns) and "outcome" in run_columns
    if extended:
        row = db.execute(
            "select t.status,t.completed_at,r.status,r.ended_at,t.body,t.block_kind,"
            "t.current_run_id,r.outcome from tasks t join task_runs r on r.task_id=t.id "
            "where t.id=? and r.id=?", (task, run),
        ).fetchone()
    else:
        row = db.execute(
            "select t.status,t.completed_at,r.status,r.ended_at,t.body "
            "from tasks t join task_runs r on r.task_id=t.id where t.id=? and r.id=?",
            (task, run),
        ).fetchone()
    comments = db.execute("select body from task_comments where task_id=?", (task,)).fetchall() if row else []
    active_origin = row and row[0] == "running" and row[1] is None and row[2] == "running" and row[3] is None
    # Phase 0 deliberately parks its originating run at a typed human gate. On
    # continuation the dispatcher starts a successor run, but the immutable
    # request remains bound to the parked run. Accept that one transition only:
    # the task must still be nonterminal, block_kind must remain needs_input,
    # and current_run_id must name a live successor for the same task. A merely
    # historical blocked run, a ready task, or a later terminal task stays dead.
    human_gate_continuation = False
    if row and extended and row[2] == "blocked" and row[3] is not None and row[7] == "blocked":
        successor = db.execute(
            "select status,ended_at,outcome from task_runs where id=? and task_id=?",
            (row[6], task),
        ).fetchone()
        human_gate_continuation = (
            row[0] == "running" and row[1] is None and row[5] == "needs_input" and
            type(row[6]) is int and row[6] != run and successor is not None and
            successor[0] == "running" and successor[1] is None and successor[2] is None
        )
    if not row or not (active_origin or human_gate_continuation):
        raise Rejected("inactive-task-run")
    if request_hash not in ((row[4] or "") + "\n" + "\n".join(str(x[0] or "") for x in comments)):
        raise Rejected("request-hash-not-canonical")


def _acquire_mutation_fence(db_path: Path, req: dict[str, Any], request_hash: str,
                            lease_seconds: float = 30.0) -> tuple[sqlite3.Connection, float]:
    """Take SQLite's canonical write fence and validate task/run under it.

    BEGIN IMMEDIATE serializes every canonical terminal transition against the
    first mutation.  It deliberately uses no broker-owned authority table: the
    Kanban database remains the sole authority and a busy/unavailable board is
    rejected rather than polled through the race.
    """
    db, _ = _open_bound_board(db_path, req, request_hash, writable=True)
    return db, time.monotonic() + lease_seconds


def _validate_mutation_fence(db: sqlite3.Connection, deadline: float,
                             req: dict[str, Any], request_hash: str) -> None:
    if time.monotonic() >= deadline:
        raise Rejected("mutation-fence-expired")
    _task_active_connection(db, req["requester_task"], req["requester_run"], request_hash)


def _durable_append(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short ledger write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def append(path: Path, record: dict[str, Any]) -> None:
    _durable_append(path, canonical(record) + b"\n")


def receipt_mac(key: bytes, body: dict[str, Any]) -> str:
    return hmac.new(key, canonical(body), hashlib.sha256).hexdigest()


def approve(req: dict[str, Any], *, db: Path, key: bytes, approvals: Path, captain_uid: int, now: int,
            queue: Path | None = None) -> dict[str, Any]:
    validate_request(req, now=now)
    rh = digest(req)
    board_db, board_identity = _open_bound_board(db, req, rh, writable=False)
    board_db.close()
    body = {"type": "captain-approval", "request_sha256": rh, "operation_id": req["operation_id"],
            "target_host": HOST, "task": req["requester_task"], "run": req["requester_run"],
            "nonce_sha256": hashlib.sha256(req["nonce"].encode()).hexdigest(), "expires_at": req["expires_at"],
            "captain_uid": captain_uid, "approved_at": now,
            "board_connection_identity": board_identity}
    rec = {**body, "mac": receipt_mac(key, body)}
    append(approvals, rec)
    if queue is not None:
        queue.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = queue.parent / f".{queue.name}.{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, canonical(req) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, queue)
        dfd = os.open(queue.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    return rec


def _records(path: Path) -> list[dict[str, Any]]:
    try:
        fd, st = _safe_regular(path, (0, os.getuid()))
        if st.st_mode & 0o022:
            os.close(fd)
            raise Rejected("unsafe-ledger-mode")
        if st.st_size > MAX_LEDGER_BYTES:
            os.close(fd)
            raise Rejected("ledger-too-large")
        try:
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(fd)
        raw = b"".join(chunks)
        if raw and not raw.endswith(b"\n"):
            raise Rejected("partial-ledger-frame")
        frames = raw.splitlines()
        if any(len(frame) > MAX_RECORD_BYTES for frame in frames):
            raise Rejected("ledger-frame-too-large")
        return [json.loads(x) for x in frames if x]
    except Rejected:
        raise
    except Exception as exc:
        raise Rejected("malformed-ledger") from exc


def _checkpoint_path(path: Path) -> Path:
    """Legacy split-checkpoint path; new generations are single-file snapshots."""
    return path.with_name(path.name + ".checkpoint")


def _checkpoint_key(key: bytes) -> bytes:
    return hmac.new(key, b"keel-ledger-checkpoint-v1", hashlib.sha256).digest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.parent / ("." + path.name + f".{os.getpid()}.{time.monotonic_ns()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short snapshot write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _verify_records(path: Path, key: bytes) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = _records(path)
    previous = "0" * 64
    for sequence, rec in enumerate(records, 1):
        if not isinstance(rec, dict) or rec.get("sequence") != sequence or rec.get("previous_hash") != previous:
            raise Rejected("ledger-chain-corrupt")
        body = {k: v for k, v in rec.items() if k not in ("record_hash", "mac")}
        record_hash = digest(body)
        if rec.get("record_hash") != record_hash or not hmac.compare_digest(str(rec.get("mac", "")), receipt_mac(key, {**body, "record_hash": record_hash})):
            raise Rejected("ledger-chain-corrupt")
        previous = record_hash
    return records


def verify_chain(path: Path, key: bytes) -> list[dict[str, Any]]:
    if not path.exists():
        if _checkpoint_path(path).exists():
            raise Rejected("ledger-checkpoint-mismatch")
        return []
    snapshot = _records(path)
    has_tip = bool(snapshot and snapshot[-1].get("type") == "ledger-snapshot-tip")
    checkpoint = snapshot[-1] if has_tip else None
    records = snapshot[:-1] if has_tip else snapshot
    # Authenticate chain records independently of the snapshot tip.
    previous = "0" * 64
    for sequence, rec in enumerate(records, 1):
        if not isinstance(rec, dict) or rec.get("sequence") != sequence or rec.get("previous_hash") != previous:
            raise Rejected("ledger-chain-corrupt")
        body_record = {k: v for k, v in rec.items() if k not in ("record_hash", "mac")}
        record_hash = digest(body_record)
        if rec.get("record_hash") != record_hash or not hmac.compare_digest(
                str(rec.get("mac", "")), receipt_mac(key, {**body_record, "record_hash": record_hash})):
            raise Rejected("ledger-chain-corrupt")
        previous = record_hash
    if not records:
        raise Rejected("ledger-checkpoint-mismatch")
    if checkpoint is None:
        raise Rejected("ledger-checkpoint-mismatch")
    body = {k: v for k, v in checkpoint.items() if k != "mac"}
    if not hmac.compare_digest(str(checkpoint.get("mac", "")), receipt_mac(_checkpoint_key(key), body)):
        raise Rejected("ledger-checkpoint-corrupt")
    terminal = records[-1]
    expected = {"type": "ledger-snapshot-tip", "version": 2,
                "generation": terminal["sequence"],
                "ledger_id": hashlib.sha256(str(path.absolute()).encode()).hexdigest(),
                "sequence": terminal["sequence"], "terminal_record_hash": terminal["record_hash"],
                "request_sha256": terminal.get("request_sha256"), "task": terminal.get("task"),
                "run": terminal.get("run"), "nonce_sha256": terminal.get("nonce_sha256"),
                "state": terminal.get("phase", terminal.get("type"))}
    if body != expected:
        raise Rejected("ledger-checkpoint-mismatch")
    return records


def append_chain(path: Path, key: bytes, body: dict[str, Any]) -> dict[str, Any]:
    prior = verify_chain(path, key) if path.exists() else []
    chained = {**body, "sequence": len(prior) + 1,
               "previous_hash": prior[-1]["record_hash"] if prior else "0" * 64}
    record_hash = digest(chained)
    rec = {**chained, "record_hash": record_hash,
           "mac": receipt_mac(key, {**chained, "record_hash": record_hash})}
    checkpoint = {"type": "ledger-snapshot-tip", "version": 2, "generation": rec["sequence"],
                  "ledger_id": hashlib.sha256(str(path.absolute()).encode()).hexdigest(),
                  "sequence": rec["sequence"], "terminal_record_hash": rec["record_hash"],
                  "request_sha256": rec.get("request_sha256"), "task": rec.get("task"),
                  "run": rec.get("run"), "nonce_sha256": rec.get("nonce_sha256"),
                  "state": rec.get("phase", rec.get("type"))}
    sealed = {**checkpoint, "mac": receipt_mac(_checkpoint_key(key), checkpoint)}
    # Records and authenticated tip are one rename-published generation.  A
    # crash exposes either the complete prior generation or complete next one.
    payload = b"".join(canonical(record) + b"\n" for record in [*prior, rec, sealed])
    _atomic_write(path, payload)
    verify_chain(path, key)
    return rec


def _event(req: dict[str, Any], kind: str, at: int) -> dict[str, Any]:
    return {"type": kind, "request_sha256": digest(req), "operation_id": req["operation_id"],
            "task": req["requester_task"], "run": req["requester_run"],
            "nonce_sha256": hashlib.sha256(req["nonce"].encode()).hexdigest(), "at": at}


def _phase(req: dict[str, Any], phase: str, at: int, **evidence: Any) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError("unknown phase")
    return {**_event(req, "operation-phase", at), "phase": phase, **evidence}


def execute(req: dict[str, Any], *, db: Path, key: bytes, approvals: Path, ledger: Path, lock: Path,
            now: int, backend: Any) -> dict[str, Any]:
    validate_request(req, now=now)
    rh = digest(req)
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        approvals_found = _records(approvals) if approvals.exists() else []
        valid = []
        for rec in approvals_found:
            body = {k: v for k, v in rec.items() if k != "mac"}
            if rec.get("request_sha256") == rh and hmac.compare_digest(str(rec.get("mac", "")), receipt_mac(key, body)):
                valid.append(rec)
        if len(valid) != 1 or valid[0]["expires_at"] <= now:
            raise Rejected("missing-or-ambiguous-approval")
        prior = verify_chain(ledger, key)
        spent = {"consumed", "mutation_started", "health_passed", "committed", "rollback_started",
                 "rollback_verified", "recovery_required"}
        if any(r.get("request_sha256") == rh and r.get("phase") in spent for r in prior):
            raise Rejected("replay")
        try:
            backend.check_pre(req)
        except Exception as exc:
            result = {**_phase(req, "preflight_rejected", int(time.time())), "ok": False,
                      "error": {"type": type(exc).__name__, "message": str(exc)}}
            append_chain(ledger, key, result)
            return result
        fence_db, board_identity = _open_bound_board(db, req, rh, writable=True)
        fence_deadline = time.monotonic() + 30.0
        mutation_started = False
        try:
            append_chain(ledger, key, _phase(req, "prepared", int(time.time()),
                                            pre_state_sha256=digest(req["expected_pre_state"]),
                                            board_connection_identity=board_identity))
            _validate_mutation_fence(fence_db, fence_deadline, req, rh)
            append_chain(ledger, key, _phase(req, "consumed", int(time.time()),
                                            approval_sha256=digest(valid[0])))
        except Exception:
            fence_db.rollback()
            fence_db.close()
            raise
        try:
            _validate_mutation_fence(fence_db, fence_deadline, req, rh)
            append_chain(ledger, key, _phase(req, "mutation_started", int(time.time())))
            _validate_mutation_fence(fence_db, fence_deadline, req, rh)
            mutation_started = True
            backend.mutate(req)
            _validate_mutation_fence(fence_db, fence_deadline, req, rh)
            health = backend.health(req)
            if not health.get("ok"):
                raise Rejected("health-failed")
            append_chain(ledger, key, _phase(req, "health_passed", int(time.time()), health=health))
            _validate_mutation_fence(fence_db, fence_deadline, req, rh)
            result = {**_phase(req, "committed", int(time.time())), "ok": True, "health": health}
        except Exception as exc:
            if not mutation_started:
                recovery = {**_phase(req, "recovery_required", int(time.time())), "ok": False,
                            "error": {"type": type(exc).__name__, "message": str(exc)}}
                append_chain(ledger, key, recovery)
                return recovery
            append_chain(ledger, key, _phase(req, "rollback_started", int(time.time())))
            rollback_evidence = None
            rollback_error = None
            try:
                rollback_evidence = backend.rollback(req)
                rollback_ok = True
            except Exception as rollback_exc:
                rollback_ok = False
                rollback_error = {"type": type(rollback_exc).__name__, "message": str(rollback_exc)}
            terminal_phase = "rollback_verified" if rollback_ok else "recovery_required"
            result = {**_phase(req, terminal_phase, int(time.time())), "ok": False,
                      "error": {"type": type(exc).__name__, "message": str(exc)},
                      "rollback_ok": rollback_ok}
            if rollback_evidence is not None:
                result["rollback_evidence"] = rollback_evidence
            if rollback_error is not None:
                result["rollback_error"] = rollback_error
        finally:
            fence_db.rollback()
            fence_db.close()
        try:
            append_chain(ledger, key, result)
        except Exception as append_exc:
            recovery = {**_phase(req, "recovery_required", int(time.time())), "ok": False,
                        "error": {"type": type(append_exc).__name__,
                                  "message": "terminal-evidence-persistence-failed"}}
            append_chain(ledger, key, recovery)
            return recovery
        return result
    finally:
        opened_fence = locals().get("fence_db")
        if opened_fence is not None:
            opened_fence.close()
        os.close(fd)


class OllamaBackend:
    def _run(self, argv: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                              capture_output=True, text=True, timeout=timeout, check=False, cwd="/")

    def _checked(self, argv: list[str], label: str, timeout: int = 45) -> subprocess.CompletedProcess[str]:
        cp = self._run(argv, timeout)
        if cp.returncode:
            raise Rejected(canonical({"failure": label, "status": cp.returncode,
                                      "stdout": cp.stdout, "stderr": cp.stderr}).decode())
        return cp

    def _show(self, prop: str) -> str:
        return self._checked(["/usr/bin/systemctl", "show", SERVICE, "--property", prop, "--value"],
                             "systemctl-show-" + prop).stdout.strip()

    def _listeners(self) -> list[dict[str, Any]]:
        cp = self._checked(["/usr/bin/ss", "-H", "-ltnp", f"sport = :{PORT}"], "listener-query")
        rows = []
        for line in cp.stdout.splitlines():
            fields = line.split()
            if len(fields) < 6:
                raise Rejected("unknown-listener-telemetry")
            endpoint = fields[3]
            address, port = endpoint.rsplit(":", 1)
            address = address.strip("[]")
            marker = "pid="
            if marker not in line:
                raise Rejected("listener-without-pid")
            pid = int(line.split(marker, 1)[1].split(",", 1)[0])
            rows.append({"address": address, "port": int(port), "pid": pid})
        return sorted(rows, key=lambda x: (x["address"], x["pid"]))

    def capture_pre_state(self, board_path: Path | None = None,
                          board_uids: tuple[int, ...] = (0,)) -> dict[str, Any]:
        fragment = Path(self._show("FragmentPath")).resolve(strict=True)
        dropin_paths = [Path(x).resolve(strict=True) for x in self._show("DropInPaths").split() if x]
        pid_text = self._show("MainPID")
        if not pid_text.isdigit() or int(pid_text) <= 0:
            raise Rejected("invalid-main-pid")
        pid = int(pid_text)
        executable = Path(f"/proc/{pid}/exe").resolve(strict=True)
        env = {}
        for item in self._show("Environment").split():
            if "=" in item:
                key, value = item.split("=", 1)
                if key in ("OLLAMA_HOST", "OLLAMA_MODELS", "CUDA_VISIBLE_DEVICES"):
                    env[key] = value
        version = self._checked([str(executable), "--version"], "version-query").stdout.strip().split()[-1]
        daemon_pids = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                candidate = (entry / "exe").resolve(strict=True)
            except (FileNotFoundError, PermissionError):
                continue
            if candidate.name == "ollama":
                daemon_pids.append(int(entry.name))
        runtime = {"service": SERVICE, "active": self._show("ActiveState") == "active",
                "fragment": str(fragment), "fragment_sha256": file_hash(fragment),
                "dropins": [{"path": str(p), "sha256": file_hash(p)} for p in dropin_paths],
                "exec_start": self._show("ExecStart").split(), "environment": env, "main_pid": pid,
                "process_executable": str(executable), "process_sha256": file_hash(executable),
                "version": version, "daemon_pids": sorted(daemon_pids),
                "listeners": self._listeners(), "model_store": MODEL_STORE,
                "model_store_manifest_sha256": tree_manifest_hash(Path(MODEL_STORE))}
        if board_path is None:
            board_path = BOARD_DB
            board_uids = (0, 1000)
        return canonical_pre_state(runtime, board_path, board_uids)

    def check_pre(self, req: dict[str, Any]) -> None:
        if socket.gethostname() != HOST or file_hash(Path(NEW_BINARY)) != NEW_SHA256:
            raise Rejected("pre-state-host-or-new-hash")
        if Path(DROPIN).exists() or Path(DROPIN).is_symlink():
            raise Rejected("dropin-exists")
        actual = self.capture_pre_state()
        if actual != req["expected_pre_state"]:
            raise Rejected("sealed-pre-state-drift")
        self._assert_local_unique(actual, OLD_BINARY, OLD_SHA256, OLD_VERSION)

    def _assert_local_unique(self, state: dict[str, Any], executable: str, sha256: str, version: str) -> None:
        if not state["active"] or state["process_executable"] != executable or state["process_sha256"] != sha256 or state["version"] != version:
            raise Rejected("runtime-identity-mismatch")
        listeners = state["listeners"]
        if state["daemon_pids"] != [state["main_pid"]]:
            raise Rejected("duplicate-or-unknown-daemon")
        if not listeners or any(x["address"] not in ("127.0.0.1", "::1") or x["port"] != PORT or x["pid"] != state["main_pid"] for x in listeners):
            raise Rejected("listener-exposure-or-owner-mismatch")
        if len({x["pid"] for x in listeners}) != 1:
            raise Rejected("duplicate-daemon")

    def _cuda_evidence(self, pid: int) -> dict[str, Any]:
        try:
            maps = Path(f"/proc/{pid}/maps").read_text()
            libraries = sorted({line.rsplit(None, 1)[-1] for line in maps.splitlines()
                                if "libcuda.so" in line or "libcublas" in line})
            devices = []
            for descriptor in Path(f"/proc/{pid}/fd").iterdir():
                try:
                    target = os.readlink(descriptor)
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                if target.startswith("/dev/nvidia"):
                    devices.append(target)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise Rejected("unknown-cuda-telemetry") from exc
        devices = sorted(set(devices))
        gpu_devices = [x for x in devices if Path(x).name.removeprefix("nvidia").isdigit()]
        if not libraries or gpu_devices != ["/dev/nvidia0"] or "/dev/nvidiactl" not in devices:
            raise Rejected("cuda-backend-not-proven")
        return {"backend": "cuda", "libraries": libraries, "devices": devices}

    def mutate(self, req: dict[str, Any]) -> None:
        if self.capture_pre_state() != req["expected_pre_state"]:
            raise Rejected("pre-mutation-drift")
        parent_fd = os.open(str(Path(DROPIN).parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(Path(DROPIN).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent_fd)
            try:
                os.write(fd, DROPIN_BYTES)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        self._checked(["/usr/bin/systemctl", "daemon-reload"], "daemon-reload")
        self._checked(["/usr/bin/systemctl", "restart", SERVICE], "restart")

    def health(self, req: dict[str, Any]) -> dict[str, Any]:
        state = self.capture_pre_state()
        self._assert_local_unique(state, NEW_BINARY, NEW_SHA256, NEW_VERSION)
        cuda = self._cuda_evidence(state["main_pid"])
        if state["model_store_manifest_sha256"] != req["expected_pre_state"]["model_store_manifest_sha256"]:
            raise Rejected("model-store-drift")
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=10) as response:
            version = json.load(response).get("version")
        if version != NEW_VERSION:
            raise Rejected("api-version-mismatch")
        payload = canonical({"model": MODEL_NAME, "prompt": "Reply exactly OK", "stream": False,
                             "options": {"temperature": 0, "num_predict": 4}})
        request = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=payload,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=90) as response:
            out = json.load(response)
        rate = out.get("eval_count", 0) / max(out.get("eval_duration", 0) / 1e9, 1e-9)
        exact_response = str(out.get("response", "")).strip() == "OK"
        ok = exact_response and rate >= 100.0
        return {"ok": ok, "version": version, "eval_tokens_per_second": rate,
                "cuda": cuda,
                "model_store_manifest_sha256": state["model_store_manifest_sha256"]}

    def rollback(self, req: dict[str, Any]) -> dict[str, Any]:
        current = self.capture_pre_state()
        expected = req["expected_pre_state"]
        current_other_dropins = [x for x in current["dropins"] if x["path"] != DROPIN]
        if (current["fragment"] != expected["fragment"] or
                current["fragment_sha256"] != expected["fragment_sha256"] or
                current_other_dropins != expected["dropins"] or
                current["model_store_manifest_sha256"] != expected["model_store_manifest_sha256"]):
            raise Rejected("rollback-target-drift")
        path = Path(DROPIN)
        parent_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                target = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                target = None
            if target is not None:
                if not stat.S_ISREG(target.st_mode) or target.st_uid != 0:
                    raise Rejected("rollback-dropin-identity")
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
                try:
                    if hashlib.sha256(os.read(fd, len(DROPIN_BYTES) + 1)).digest() != hashlib.sha256(DROPIN_BYTES).digest():
                        raise Rejected("rollback-dropin-unsealed")
                finally:
                    os.close(fd)
                os.unlink(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        commands = []
        for argv, label in ((["/usr/bin/systemctl", "daemon-reload"], "rollback-daemon-reload"),
                            (["/usr/bin/systemctl", "restart", SERVICE], "rollback-restart")):
            cp = self._run(argv)
            evidence = {"argv": argv, "status": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}
            commands.append(evidence)
            if cp.returncode:
                raise Rejected(canonical({"failure": label, **evidence}).decode())
        restored = self.capture_pre_state()
        stable_keys = PRE_STATE_KEYS - {"main_pid", "daemon_pids", "listeners"}
        stable_match = all(restored[key] == expected[key] for key in stable_keys)
        expected_listener_addresses = sorted((x["address"], x["port"]) for x in expected["listeners"])
        restored_listener_addresses = sorted((x["address"], x["port"]) for x in restored["listeners"])
        if not stable_match or restored_listener_addresses != expected_listener_addresses:
            raise Rejected(canonical({"failure": "rollback-post-state-mismatch",
                                      "expected_sha256": digest(expected), "actual_sha256": digest(restored)}).decode())
        self._assert_local_unique(restored, OLD_BINARY, OLD_SHA256, OLD_VERSION)
        return {"commands": commands, "restored_pre_state_sha256": digest(restored)}
