#!/usr/bin/python3
"""Reviewed, argument-free Phase-0 bootstrap for the Keel v2 ceremony.

Production authority is deliberately closed over constants below.  Test overrides are
accepted only with KEEL_PHASE0_ROOTLESS_FIXTURE=1 and never by a real-root process.
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
import subprocess
import sys
import time
from pathlib import Path

SOURCE = Path("/var/tmp/hermes-keel-phase0-package-t_912db980-r186")
MANIFEST_SHA256 = "c74d21bd4f3204ae16c9d7c4e53a420ce15e58ef0e16bdeecf45ffd7a6827aec"
TASK = "t_912db980"
RUN = 186
CAPTAIN_UID = 1000
TRUSTED_ROOT = Path("/root/hermes-keel-staging/t_912db980-r186")
INSTALL_ROOT = Path("/")
BOARD = Path("/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db")
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
        return SOURCE, TRUSTED_ROOT, INSTALL_ROOT, BOARD, TASK, RUN, CAPTAIN_UID
    # Overrides are a rootless test seam, never a production input surface.
    return (Path(os.environ["KEEL_PHASE0_SOURCE"]), Path(os.environ["KEEL_PHASE0_TRUSTED_ROOT"]),
            Path(os.environ["KEEL_PHASE0_INSTALL_ROOT"]), Path(os.environ["KEEL_PHASE0_BOARD"]),
            os.environ.get("KEEL_PHASE0_TASK", TASK), int(os.environ.get("KEEL_PHASE0_RUN", RUN)), os.getuid())

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

def _open_source(source: Path, owner: int) -> tuple[int, dict[str, bytes]]:
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if st.st_uid != owner or st.st_mode & 0o022:
            raise Rejected("unsafe-source-root")
        manifest, _ = _read_regular(fd, "MANIFEST", owner)
        if _sha(manifest) != MANIFEST_SHA256:
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

def _seal(source: Path, trusted_root: Path, owner: int, fail: str | None) -> Path:
    source_fd, blobs = _open_source(source, owner)
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
    source, trusted, install_root, board, task, run, captain_uid = _configuration()
    fail = os.environ.get("KEEL_PHASE0_FAIL_AFTER") if _fixture() else None
    package = None
    sealed_this_run = False
    installed_this_run = False
    request = install_root / "var/lib/hermes-privileged-broker/requests" / REQUEST_NAME
    receipt = install_root / "var/lib/hermes-privileged-broker/phase0-audit.json"
    try:
        if receipt.is_file() and request.is_file():
            audit = json.loads(receipt.read_text())
            request_bytes = request.read_bytes()
            if (audit.get("schema") != "keel.phase0-bootstrap-receipt.v1" or
                    audit.get("manifest_sha256") != MANIFEST_SHA256 or
                    _sha(request_bytes.rstrip(b"\n")) != audit.get("request_sha256")):
                raise Rejected("existing-phase0-receipt-drift")
            print(json.dumps(audit, indent=2, sort_keys=True))
            print("PHASE-1 REQUEST SHA-256: " + audit["request_sha256"])
            print("Phase-0 already complete; no authority or request was recreated.")
            return 0
        package = _seal(source, trusted, captain_uid, fail)
        sealed_this_run = True
        if fail == "trusted-publication": raise Rejected("injected-trusted-publication")
        env = dict(os.environ)
        if _fixture():
            env.update(KEEL_ROOTLESS_FIXTURE="1", KEEL_INSTALL_ROOT=str(install_root),
                       KEEL_TRUST_ROOT=str(trusted.parent), KEEL_TRUST_UID=str(captain_uid))
        cp = subprocess.run(["/bin/sh", str(package / "install.sh"), str(package), MANIFEST_SHA256],
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
                           pre_state=pre_state, package=sealed_package(str(package), MANIFEST_SHA256))
        request.parent.mkdir(mode=0o700, exist_ok=True)
        _write_exclusive(request, canonical(req) + b"\n", 0o400)
        request_hash = digest(req)
        audit = {"schema":"keel.phase0-bootstrap-receipt.v1", "acceptanceClaim":False,
                 "phase1_schema":"ollama-system-runtime-switch-v2", "task":task, "run":run,
                 "sealed_package":str(package), "manifest_sha256":MANIFEST_SHA256,
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

if __name__ == "__main__":
    raise SystemExit(main())
