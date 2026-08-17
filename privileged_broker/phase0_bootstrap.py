#!/usr/bin/python3
"""Reviewed, argument-free Phase-0 bootstrap for the Keel v2 ceremony.

Production authority reads one immutable ceremony binding at one fixed path. Test
overrides are accepted only with KEEL_PHASE0_ROOTLESS_FIXTURE=1 and never by root.
This program installs authority and emits a request; it cannot approve, execute,
restart, or otherwise address systemd/Ollama mutation interfaces.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

CAPTAIN_UID = 1000
INSTALL_ROOT = Path("/")
BOARD = Path("/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db")
BINDING = Path("/var/tmp/hermes-keel-phase0-binding.json")
HOST = "groot"
ACTION = "ollama-system-runtime-switch-v2"
REQUEST_NAME = "phase1-ollama-system-runtime-switch-v2.json"
MEMBERS = ("MANIFEST", "core.py", "broker.py", "package_v2.py", "hermes-privileged-broker.sudoers",
           "install.sh", "uninstall.sh", "runtime/ollama")

class Rejected(RuntimeError):
    pass

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _fixture() -> bool:
    return os.environ.get("KEEL_PHASE0_ROOTLESS_FIXTURE") == "1" and os.geteuid() != 0

def _configuration():
    # Phase-0 is a fixed ceremony entrypoint, including in the rootless test
    # seam.  Reject argv before selecting either configuration branch so an
    # override can never broaden the production interface.
    if len(sys.argv) != 1:
        raise Rejected("phase0-accepts-no-arguments")
    if not _fixture():
        if os.geteuid() != 0:
            raise Rejected("root-required")
        return BINDING, INSTALL_ROOT, CAPTAIN_UID
    # Overrides are a rootless test seam, never a production input surface.
    return (Path(os.environ["KEEL_PHASE0_BINDING"]),
            Path(os.environ["KEEL_PHASE0_INSTALL_ROOT"]), os.getuid())

def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

def _read_binding(path: Path, owner: int) -> tuple[dict, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022:
            raise Rejected("unsafe-binding")
        raw = b""
        while chunk := os.read(fd, 65536):
            raw += chunk
            if len(raw) > 65536: raise Rejected("binding-too-large")
    finally:
        os.close(fd)
    try: packet = json.loads(raw)
    except Exception as exc: raise Rejected("bad-binding-json") from exc
    keys = {"schema","task","run","board","board_identity","host","source","manifest_sha256",
            "action","nonce","created_at","expires_at","packet_sha256"}
    if not isinstance(packet, dict) or set(packet) != keys or packet.get("schema") != "keel.phase0-binding.v1":
        raise Rejected("bad-binding-schema")
    body = {k:v for k,v in packet.items() if k != "packet_sha256"}
    packet_hash = _sha(_canonical(body))
    if packet["packet_sha256"] != packet_hash: raise Rejected("binding-hash-mismatch")
    now = int(time.time())
    if (packet["host"] != HOST or packet["action"] != ACTION or (not _fixture() and packet["board"] != str(BOARD)) or
            type(packet["run"]) is not int or packet["run"] <= 0 or
            not isinstance(packet["task"], str) or not packet["task"].startswith("t_") or
            not isinstance(packet["nonce"], str) or len(packet["nonce"]) < 32 or
            type(packet["created_at"]) is not int or type(packet["expires_at"]) is not int or
            packet["created_at"] > now or packet["expires_at"] <= now or
            packet["expires_at"] <= packet["created_at"] or packet["expires_at"]-packet["created_at"] > 3600 or
            not isinstance(packet["source"], str) or not Path(packet["source"]).is_absolute() or
            (not _fixture() and Path(packet["source"]).parent != Path("/var/tmp")) or
            not isinstance(packet["manifest_sha256"], str) or len(packet["manifest_sha256"]) != 64 or
            any(c not in "0123456789abcdef" for c in packet["manifest_sha256"])):
        raise Rejected("invalid-binding")
    return packet, packet_hash

def _open_ceremony_fence(packet: dict, packet_hash: str, fixture: bool):
    board = Path(packet["board"])
    fd = os.open(board, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        db = sqlite3.connect(f"file:/proc/self/fd/{fd}?mode=rw", uri=True, timeout=0, isolation_level=None)
        db.execute("begin immediate")
        schema = _sha(_canonical(db.execute("select type,name,tbl_name,sql from sqlite_master order by type,name").fetchall()))
        identity = {"device":st.st_dev,"inode":st.st_ino,"uid":st.st_uid,"mode":stat.S_IMODE(st.st_mode),
                    "schema_sha256":schema}
        if not isinstance(packet["board_identity"], dict): raise Rejected("bad-board-identity")
        if not fixture and identity != packet["board_identity"]: raise Rejected("binding-board-drift")
        row=db.execute("select t.status,t.completed_at,t.block_kind,r.status,r.ended_at,r.outcome,t.body "
                       "from tasks t join task_runs r on r.task_id=t.id where t.id=? and r.id=?",
                       (packet["task"],packet["run"])).fetchone()
        comments=db.execute("select body from task_comments where task_id=?",(packet["task"],)).fetchall() if row else []
        running = row and row[0]=="running" and row[1] is None and row[3]=="running" and row[4] is None
        human_gate = row and row[0]=="blocked" and row[1] is None and row[2]=="needs_input" and row[3]=="blocked" and row[4] is not None and row[5]=="blocked"
        canonical_text = (row[6] or "") + "\n" + "\n".join(str(x[0] or "") for x in comments) if row else ""
        if not (running or human_gate) or packet_hash not in canonical_text:
            raise Rejected("inactive-or-unauthorized-binding")
        return db
    except Exception:
        opened = locals().get("db")
        if opened is not None: opened.close()
        raise
    finally: os.close(fd)

def _read_regular(parent_fd: int, name: str, owner: int) -> tuple[bytes, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022:
            raise Rejected("unsafe-source-member:" + name)
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), st
    finally:
        os.close(fd)

def _open_source(source: Path, owner: int, manifest_sha256: str) -> tuple[int, dict[str, bytes]]:
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if st.st_uid != owner or st.st_mode & 0o022:
            raise Rejected("unsafe-source-root")
        manifest, _ = _read_regular(fd, "MANIFEST", owner)
        if _sha(manifest) != manifest_sha256:
            raise Rejected("manifest-hash-mismatch")
        rows = {}
        for line in manifest.decode("ascii").splitlines():
            digest, marker, name = line.partition("  ")
            if marker != "  " or name in rows:
                raise Rejected("bad-manifest")
            rows[name] = digest
        if set(rows) != set(MEMBERS[1:]):
            raise Rejected("manifest-members-mismatch")
        blobs = {"MANIFEST": manifest}
        for name in MEMBERS[1:]:
            data, _ = _read_regular(fd, name, owner)
            if _sha(data) != rows[name]:
                raise Rejected("member-hash-mismatch:" + name)
            blobs[name] = data
        return fd, blobs
    except Exception:
        os.close(fd)
        raise

def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        os.write(fd, data); os.fsync(fd)
    finally:
        os.close(fd)

def _seal(source: Path, trusted_root: Path, owner: int, fail: str | None, manifest_sha256: str) -> Path:
    source_fd, blobs = _open_source(source, owner, manifest_sha256)
    stage = trusted_root.with_name(trusted_root.name + ".stage")
    try:
        if trusted_root.exists() or trusted_root.is_symlink() or stage.exists() or stage.is_symlink():
            raise Rejected("trusted-staging-collision")
        stage.mkdir(parents=True, mode=0o700)
        (stage / "package/runtime").mkdir(parents=True, mode=0o700)
        for name, data in blobs.items():
            target = stage / "package" / name
            _write_exclusive(target, data, 0o444)
        if fail == "sealed-copy": raise Rejected("injected-sealed-copy")
        # Source descriptors remained open through the complete copy; re-read all
        # identities before publication so source replacement cannot be accepted.
        for name, data in blobs.items():
            current, _ = _read_regular(source_fd, name, owner)
            if current != data: raise Rejected("source-drift:" + name)
        for path in (stage / "package/runtime", stage / "package"): path.chmod(0o555)
        stage.chmod(0o500)
        os.replace(stage, trusted_root)
        return trusted_root / "package"
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        os.close(source_fd)

def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def _remove_tree(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        path.unlink(missing_ok=True); return
    for directory, directories, _ in os.walk(path):
        Path(directory).chmod(0o700)
        for child in directories: (Path(directory) / child).chmod(0o700)
    shutil.rmtree(path)

def main() -> int:
    binding_path, install_root, captain_uid = _configuration()
    fail = os.environ.get("KEEL_PHASE0_FAIL_AFTER") if _fixture() else None
    packet, packet_hash = _read_binding(binding_path, captain_uid)
    source = Path(packet["source"]); board = Path(packet["board"])
    task = packet["task"]; run = packet["run"]; manifest_sha256 = packet["manifest_sha256"]
    trusted = (Path(os.environ["KEEL_PHASE0_TRUSTED_ROOT"]) if _fixture() else
               Path(f"/root/hermes-keel-staging/{task}-r{run}-{packet_hash[:16]}"))
    package = None
    sealed_this_run = False
    installed_this_run = False
    request = install_root / "var/lib/hermes-privileged-broker/requests" / REQUEST_NAME
    receipt = install_root / "var/lib/hermes-privileged-broker/phase0-audit.json"
    fence = None
    try:
        fence = _open_ceremony_fence(packet, packet_hash, _fixture())
        if receipt.is_file() and request.is_file():
            audit = json.loads(receipt.read_text())
            request_bytes = request.read_bytes()
            if (audit.get("schema") != "keel.phase0-bootstrap-receipt.v1" or
                    audit.get("manifest_sha256") != manifest_sha256 or audit.get("binding_sha256") != packet_hash or
                    _sha(request_bytes.rstrip(b"\n")) != audit.get("request_sha256")):
                raise Rejected("existing-phase0-receipt-drift")
            print(json.dumps(audit, indent=2, sort_keys=True))
            print("PHASE-1 REQUEST SHA-256: " + audit["request_sha256"])
            print("Phase-0 already complete; no authority or request was recreated.")
            return 0
        package = _seal(source, trusted, captain_uid, fail, manifest_sha256)
        sealed_this_run = True
        if fail == "trusted-publication": raise Rejected("injected-trusted-publication")
        env = dict(os.environ)
        if _fixture():
            env.update(KEEL_ROOTLESS_FIXTURE="1", KEEL_INSTALL_ROOT=str(install_root),
                       KEEL_TRUST_ROOT=str(trusted.parent), KEEL_TRUST_UID=str(captain_uid))
        cp = subprocess.run(["/bin/sh", str(package / "install.sh"), str(package), manifest_sha256],
                            env=env, text=True, capture_output=True, check=False)
        if cp.returncode:
            raise Rejected("installer-failed:" + cp.stderr.strip())
        installed_this_run = True
        if fail == "installed": raise Rejected("injected-installed")
        lib = install_root / "usr/local/lib/hermes-privileged-broker"
        sys.path.insert(0, str(lib))
        from core import OllamaBackend, canonical, digest, make_request, sealed_package
        if _fixture() and os.environ.get("KEEL_PHASE0_PRESTATE"):
            pre_state = json.loads(Path(os.environ["KEEL_PHASE0_PRESTATE"]).read_text())
        else:
            pre_state = OllamaBackend().capture_pre_state(board, (captain_uid,))
        req = make_request(task, run, secrets.token_urlsafe(32), int(time.time()), ttl=1800,
                           pre_state=pre_state, package=sealed_package(str(package), manifest_sha256))
        request.parent.mkdir(mode=0o700, exist_ok=True)
        _write_exclusive(request, canonical(req) + b"\n", 0o400)
        request_hash = digest(req)
        audit = {"schema":"keel.phase0-bootstrap-receipt.v1", "acceptanceClaim":False,
                 "phase1_schema":"ollama-system-runtime-switch-v2", "task":task, "run":run,
                 "sealed_package":str(package), "manifest_sha256":manifest_sha256,
                 "binding_sha256":packet_hash,
                 "request":str(request), "request_sha256":request_hash,
                 "effects":{"broker_installed":True,"ollama_mutated":False,"authorization_consumed":False}}
        _write_exclusive(receipt, json.dumps(audit, sort_keys=True, separators=(",", ":")).encode()+b"\n", 0o400)
        _fsync_dir(request.parent)
        print(json.dumps(audit, indent=2, sort_keys=True))
        print("PHASE-1 REQUEST SHA-256: " + request_hash)
        return 0
    except Exception as exc:
        # A failed bootstrap never leaves newly installed authority or trusted input.
        if installed_this_run and (install_root != Path("/") or _fixture()):
            for rel in ("etc/sudoers.d/hermes-privileged-broker", "usr/local/sbin/hermes-privileged-broker"):
                (install_root / rel).unlink(missing_ok=True)
            for rel in ("usr/local/lib/hermes-privileged-broker", "var/lib/hermes-privileged-broker"):
                shutil.rmtree(install_root / rel, ignore_errors=True)
        if sealed_this_run:
            _remove_tree(trusted)
        print("phase0 rejected: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if fence is not None:
            fence.rollback(); fence.close()

if __name__ == "__main__":
    raise SystemExit(main())
