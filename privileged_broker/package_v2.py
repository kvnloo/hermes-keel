#!/usr/bin/env python3
"""Content-addressed v2 package builder/verifier and rootless ceremony rehearsal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Callable

from privileged_broker import core

MEMBERS = ("core.py", "broker.py", "package_v2.py", "hermes-privileged-broker.sudoers", "install.sh", "uninstall.sh", "runtime/ollama")


class PackageRejected(RuntimeError):
    pass


def hash_fd(fd: int) -> str:
    h = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        h.update(chunk)
    return h.hexdigest()


def _open_member(root_fd: int, name: str) -> tuple[int, os.stat_result]:
    if name.startswith("/") or ".." in Path(name).parts:
        raise PackageRejected("unsafe-member")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022:
        os.close(fd)
        raise PackageRejected("unsafe-member-identity")
    return fd, st


def verify(package: Path, expected_manifest: str, allowed_uid: int | None = None) -> dict:
    root_fd = os.open(package, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        root_st = os.fstat(root_fd)
        if allowed_uid is not None and root_st.st_uid != allowed_uid:
            raise PackageRejected("wrong-package-owner")
        manifest_fd, _ = _open_member(root_fd, "MANIFEST")
        try:
            manifest_bytes = b""
            while chunk := os.read(manifest_fd, 64 * 1024):
                manifest_bytes += chunk
            if len(manifest_bytes) > 64 * 1024:
                raise PackageRejected("manifest-too-large")
        finally:
            os.close(manifest_fd)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != expected_manifest:
            raise PackageRejected("manifest-hash-mismatch")
        rows = {}
        for raw in manifest_bytes.decode("ascii").splitlines():
            digest, marker, name = raw.partition("  ")
            if marker != "  " or name in rows or name not in MEMBERS or len(digest) != 64:
                raise PackageRejected("bad-manifest")
            rows[name] = digest
        if set(rows) != set(MEMBERS):
            raise PackageRejected("incomplete-manifest")
        identities = {}
        for name in MEMBERS:
            fd, st = _open_member(root_fd, name)
            try:
                actual = hash_fd(fd)
            finally:
                os.close(fd)
            if actual != rows[name]:
                raise PackageRejected("member-hash-mismatch")
            identities[name] = {"sha256": actual, "size": st.st_size, "device": st.st_dev, "inode": st.st_ino}
        if rows["runtime/ollama"] != core.NEW_SHA256:
            raise PackageRejected("wrong-runtime")
        return {"manifest_sha256": manifest_hash, "members": identities}
    finally:
        os.close(root_fd)


def build(source: Path, runtime: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink() or not output.is_absolute():
        raise PackageRejected("output-must-be-new-absolute")
    runtime_fd = os.open(runtime, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if hash_fd(runtime_fd) != core.NEW_SHA256:
            raise PackageRejected("wrong-runtime")
    finally:
        os.close(runtime_fd)
    output.mkdir(mode=0o700)
    try:
        (output / "runtime").mkdir(mode=0o700)
        for name in MEMBERS:
            src = runtime if name == "runtime/ollama" else source / name
            dst = output / name
            shutil.copyfile(src, dst, follow_symlinks=False)
            dst.chmod(0o444)
        lines = []
        for name in MEMBERS:
            lines.append(f"{hashlib.sha256((output / name).read_bytes()).hexdigest()}  {name}\n")
        manifest = output / "MANIFEST"
        manifest.write_text("".join(lines), encoding="ascii")
        manifest.chmod(0o444)
        (output / "runtime").chmod(0o555)
        output.chmod(0o555)
        mh = hashlib.sha256(manifest.read_bytes()).hexdigest()
        marker = output / "MANIFEST.sha256"
        output.chmod(0o755)
        marker.write_text(mh + "\n", encoding="ascii")
        marker.chmod(0o444)
        output.chmod(0o555)
        evidence = verify(output, mh, os.getuid())
        evidence.update({"schema": "keel.sealed-package.v2", "action": core.ACTION,
                         "package": str(output), "runtime_install_path": core.NEW_BINARY})
        return evidence
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def rehearse(package: Path, manifest_hash: str, root: Path, fail_at: str | None = None) -> dict:
    """No-root transaction model. Every injected failure must leave no publication."""
    evidence = verify(package, manifest_hash, os.getuid())
    lib = root / "usr/local/lib/hermes-privileged-broker"
    policy = root / "etc/sudoers.d/hermes-privileged-broker"
    launcher = root / "usr/local/sbin/hermes-privileged-broker"
    state = root / "var/lib/hermes-privileged-broker"
    published: list[Path] = []
    stage = root / ".keel-v2-stage"
    try:
        stage.mkdir(parents=True)
        stage.chmod(0o700)
        if fail_at == "stage": raise PackageRejected("injected-stage")
        shutil.copytree(package, stage / "lib", dirs_exist_ok=True)
        (stage / "lib").chmod(0o700)
        (stage / "lib" / "runtime").chmod(0o700)
        runtime_dest = stage / "lib" / "runtimes" / f"sha256-{core.NEW_SHA256}"
        runtime_dest.mkdir(parents=True)
        os.replace(stage / "lib" / "runtime" / "ollama", runtime_dest / "ollama")
        (stage / "lib" / "runtime").rmdir()
        if fail_at == "copy": raise PackageRejected("injected-copy")
        lib.parent.mkdir(parents=True, exist_ok=True); lib.parent.chmod(0o700)
        os.replace(stage / "lib", lib); lib.chmod(0o555); published.append(lib)
        if fail_at == "library": raise PackageRejected("injected-library")
        launcher.parent.mkdir(parents=True, exist_ok=True); launcher.symlink_to(lib / "broker.py"); published.append(launcher)
        if fail_at == "launcher": raise PackageRejected("injected-launcher")
        state.mkdir(parents=True, mode=0o700); published.append(state)
        (state / "approval.key").write_bytes(b"R" * 32)
        if fail_at == "state": raise PackageRejected("injected-state")
        policy.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(package / "hermes-privileged-broker.sudoers", policy); published.append(policy)
        if fail_at == "policy": raise PackageRejected("injected-policy")
        return {"ok": True, "package": evidence, "published": [str(x.relative_to(root)) for x in published]}
    except Exception:
        for path in reversed(published):
            if path.is_dir() and not path.is_symlink():
                for directory, directories, _ in os.walk(path):
                    Path(directory).chmod(0o700)
                    for child in directories:
                        (Path(directory) / child).chmod(0o700)
                shutil.rmtree(path, ignore_errors=True)
            else: path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build"); b.add_argument("--runtime", type=Path, required=True); b.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("verify"); v.add_argument("--package", type=Path, required=True); v.add_argument("--manifest", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    result = build(source, args.runtime, args.output) if args.command == "build" else verify(args.package, args.manifest, os.getuid())
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
