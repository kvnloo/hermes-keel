import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from privileged_broker import core, package_v2

NOW = 2_000_000_000


class Backend:
    def __init__(self): self.calls = []
    def check_pre(self, req): self.calls.append("pre")
    def mutate(self, req): self.calls.append("mutate")
    def health(self, req): self.calls.append("health"); return {"ok": True}


class V2GateRepairTests(unittest.TestCase):
    def test_canonical_pre_state_has_exact_runtime_and_board_shape(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "board.db"
            sqlite3.connect(db_path).close()
            runtime = dict(core.fixture_pre_state())
            runtime.pop("board_identity")
            actual = core.canonical_pre_state(runtime, db_path, (os.getuid(),))
            self.assertEqual(set(actual), core.PRE_STATE_KEYS)
            self.assertEqual(actual["board_identity"], core.file_identity(db_path, (os.getuid(),)))
            changed = dict(actual); changed["main_pid"] += 1
            self.assertNotEqual(core.canonical(actual), core.canonical(changed))

    def _bound(self, root: Path):
        db_path = root / "kanban.db"
        db = sqlite3.connect(db_path)
        db.executescript("create table tasks(id text,status text,completed_at int,body text);"
                         "create table task_runs(id int,task_id text,status text,ended_at int);"
                         "create table task_comments(task_id text,body text);")
        db.commit(); db.close()
        pre = dict(core.fixture_pre_state())
        pre["board_identity"] = core.file_identity(db_path, (os.getuid(),))
        req = core.make_request("t_bound", 9, "B" * 32, NOW, pre_state=pre)
        db = sqlite3.connect(db_path)
        db.execute("insert into tasks values(?,?,?,?)", ("t_bound", "running", None, core.digest(req)))
        db.execute("insert into task_runs values(?,?,?,?)", (9, "t_bound", "running", None))
        db.commit(); db.close()
        return db_path, req

    def test_approve_and_execute_revalidate_authoritative_board(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path, req = self._bound(root)
            key = b"K" * 32; approvals = root / "approvals"
            core.approve(req, db=db_path, key=key, approvals=approvals, captain_uid=os.getuid(), now=NOW)
            backend = Backend()
            out = core.execute(req, db=db_path, key=key, approvals=approvals,
                               ledger=root / "ledger", lock=root / "lock", now=NOW, backend=backend)
            self.assertTrue(out["ok"]); self.assertEqual(backend.calls, ["pre", "mutate", "health"])

    def test_board_path_schema_and_inode_substitution_reject(self):
        for drift in ("path", "schema", "replacement"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as td:
                root = Path(td); db_path, req = self._bound(root)
                if drift == "path":
                    other = root / "other.db"; other.write_bytes(db_path.read_bytes()); candidate = other
                elif drift == "schema":
                    sqlite3.connect(db_path).execute("create table attacker(x)").connection.commit(); candidate = db_path
                else:
                    old = root / "old.db"; db_path.rename(old); db_path.write_bytes(old.read_bytes()); candidate = db_path
                with self.assertRaisesRegex(core.Rejected, "authoritative-board-drift"):
                    core.validate_board_authority(candidate, req, core.digest(req))

    def test_actual_installer_failure_cleanup_and_ancestor_policy(self):
        with tempfile.TemporaryDirectory() as td:
            trust = Path(td); trust.chmod(0o700)
            runtime = trust / "runtime"; runtime.write_bytes(b"runtime\n")
            old_hash, old_binary = core.NEW_SHA256, core.NEW_BINARY
            try:
                core.NEW_SHA256 = __import__("hashlib").sha256(runtime.read_bytes()).hexdigest()
                core.NEW_BINARY = f"/usr/local/lib/hermes-privileged-broker/runtimes/sha256-{core.NEW_SHA256}/ollama"
                package = trust / "package"
                evidence = package_v2.build(Path(package_v2.__file__).parent, runtime, package)
            finally:
                core.NEW_SHA256, core.NEW_BINARY = old_hash, old_binary
            installer = package / "install.sh"
            for phase in ("library", "launcher", "state", "key", "policy"):
                fixture = trust / ("fixture-" + phase)
                shared = {"usr/local/lib": 0o755, "usr/local/sbin": 0o711,
                          "etc/sudoers.d": 0o750, "var/lib": 0o755, "var/tmp": 0o1777}
                for rel, mode in shared.items():
                    parent = fixture / rel
                    parent.mkdir(parents=True, exist_ok=True)
                    parent.chmod(mode)
                before = {rel: (fixture / rel).stat().st_mode & 0o7777 for rel in shared}
                env = {**os.environ, "KEEL_ROOTLESS_FIXTURE": "1", "KEEL_INSTALL_ROOT": str(fixture),
                       "KEEL_TRUST_ROOT": str(trust), "KEEL_TRUST_UID": str(os.getuid()),
                       "KEEL_FAIL_AFTER": phase}
                cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                    env=env, capture_output=True, text=True)
                self.assertEqual(cp.returncode, 97, cp.stderr)
                self.assertEqual(before, {rel: (fixture / rel).stat().st_mode & 0o7777 for rel in shared})
                for rel in ("usr/local/lib/hermes-privileged-broker", "usr/local/sbin/hermes-privileged-broker",
                            "etc/sudoers.d/hermes-privileged-broker", "var/lib/hermes-privileged-broker"):
                    self.assertFalse((fixture / rel).exists(), (phase, rel))
            fixture = trust / "fixture-success"
            for rel, mode in shared.items():
                parent = fixture / rel
                parent.mkdir(parents=True, exist_ok=True)
                parent.chmod(mode)
            before = {rel: (fixture / rel).stat().st_mode & 0o7777 for rel in shared}
            cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1",
                                     "KEEL_INSTALL_ROOT": str(fixture),
                                     "KEEL_TRUST_ROOT": str(trust),
                                     "KEEL_TRUST_UID": str(os.getuid())},
                                capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual(before, {rel: (fixture / rel).stat().st_mode & 0o7777 for rel in shared})
            # Destination policy covers the complete root-to-parent chain, not
            # merely the immediate shared parent and not the package source.
            for unsafe_rel, mode in (("usr", 0o777), ("usr/local", 0o775)):
                bad = trust / ("bad-" + unsafe_rel.replace("/", "-"))
                for rel, safe_mode in shared.items():
                    parent = bad / rel
                    parent.mkdir(parents=True, exist_ok=True); parent.chmod(safe_mode)
                (bad / unsafe_rel).chmod(mode)
                cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                    env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1",
                                         "KEEL_INSTALL_ROOT": str(bad), "KEEL_TRUST_ROOT": str(trust),
                                         "KEEL_TRUST_UID": str(os.getuid())}, capture_output=True, text=True)
                self.assertNotEqual(cp.returncode, 0); self.assertIn("writable install ancestor", cp.stderr)
                self.assertFalse((bad / "usr/local/lib/hermes-privileged-broker").exists())
            bad = trust / "bad-symlink"; outside = trust / "outside"; outside.mkdir()
            bad.mkdir(); (bad / "usr").symlink_to(outside, target_is_directory=True)
            cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1", "KEEL_INSTALL_ROOT": str(bad),
                                     "KEEL_TRUST_ROOT": str(trust), "KEEL_TRUST_UID": str(os.getuid())},
                                capture_output=True, text=True)
            self.assertNotEqual(cp.returncode, 0); self.assertIn("symlink or unsafe install ancestor", cp.stderr)
            race = trust / "bad-race"
            for rel, safe_mode in shared.items():
                parent = race / rel; parent.mkdir(parents=True, exist_ok=True); parent.chmod(safe_mode)
            cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1", "KEEL_INSTALL_ROOT": str(race),
                                     "KEEL_TRUST_ROOT": str(trust), "KEEL_TRUST_UID": str(os.getuid()),
                                     "KEEL_TEST_BEFORE_WRITE_FENCE": f"chmod 0777 {race / 'usr/local'}"},
                                capture_output=True, text=True)
            self.assertNotEqual(cp.returncode, 0); self.assertIn("writable install ancestor", cp.stderr)
            self.assertFalse((race / "usr/local/lib/hermes-privileged-broker").exists())
            owner_bad = trust / "bad-owner"
            for rel, safe_mode in shared.items():
                parent = owner_bad / rel; parent.mkdir(parents=True, exist_ok=True); parent.chmod(safe_mode)
            cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1",
                                     "KEEL_INSTALL_ROOT": str(owner_bad), "KEEL_TRUST_ROOT": str(trust),
                                     "KEEL_TRUST_UID": str(os.getuid()),
                                     "KEEL_TEST_DESTINATION_TRUST_UID": str(os.getuid() + 1)},
                                capture_output=True, text=True)
            self.assertNotEqual(cp.returncode, 0); self.assertIn("untrusted install ancestor owner", cp.stderr)
            self.assertFalse((owner_bad / "usr/local/lib/hermes-privileged-broker").exists())
            trust.chmod(0o722)
            cp = subprocess.run(["/bin/sh", str(installer), str(package), evidence["manifest_sha256"]],
                                env={**os.environ, "KEEL_ROOTLESS_FIXTURE": "1", "KEEL_INSTALL_ROOT": str(trust / "bad"),
                                     "KEEL_TRUST_ROOT": str(trust), "KEEL_TRUST_UID": str(os.getuid())},
                                capture_output=True, text=True)
            self.assertNotEqual(cp.returncode, 0); self.assertIn("writable package ancestor", cp.stderr)

    def test_symlink_and_preopen_replacement_never_reach_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path, req = self._bound(root)
            key = b"R" * 32; approvals = root / "approvals"
            core.approve(req, db=db_path, key=key, approvals=approvals,
                         captain_uid=os.getuid(), now=NOW)
            original = root / "original.db"
            db_path.rename(original)
            db_path.write_bytes(original.read_bytes())
            backend = Backend()
            with self.assertRaisesRegex(core.Rejected, "authoritative-board-drift"):
                core.execute(req, db=db_path, key=key, approvals=approvals,
                             ledger=root / "ledger", lock=root / "lock", now=NOW, backend=backend)
            self.assertEqual(backend.calls, ["pre"])
            db_path.unlink(); db_path.symlink_to(original)
            with self.assertRaisesRegex(core.Rejected, "unsafe-board"):
                core.execute(req, db=db_path, key=key, approvals=approvals,
                             ledger=root / "ledger2", lock=root / "lock2", now=NOW, backend=backend)
            self.assertEqual(backend.calls, ["pre", "pre"])


if __name__ == "__main__": unittest.main()
