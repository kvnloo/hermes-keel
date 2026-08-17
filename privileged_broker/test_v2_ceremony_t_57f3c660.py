import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core, package_v2


class V2CeremonyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "source-runtime"
        self.runtime.write_bytes(b"synthetic reviewed runtime\n")
        self.runtime_hash = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        self.package = self.root / "sealed-package"
        self.source = Path(package_v2.__file__).parent
        self.patch_hash = mock.patch.object(core, "NEW_SHA256", self.runtime_hash)
        self.patch_binary = mock.patch.object(
            core, "NEW_BINARY",
            f"/usr/local/lib/hermes-privileged-broker/runtimes/sha256-{self.runtime_hash}/ollama",
        )
        self.patch_hash.start(); self.patch_binary.start()
        self.evidence = package_v2.build(self.source, self.runtime, self.package)

    def tearDown(self):
        self.patch_binary.stop(); self.patch_hash.stop(); self.temp.cleanup()

    def test_v1_and_historical_packets_are_rejected(self):
        req = core.make_request("t_v2", 1, "V" * 32, 2_000_000_000)
        for change in ({"version": 1}, {"action": "ollama-system-runtime-switch-v1"}):
            old = dict(req); old.update(change)
            with self.assertRaises(core.Rejected): core.validate_request(old, now=2_000_000_000)
        old = dict(req); old.pop("sealed_package")
        with self.assertRaisesRegex(core.Rejected, "bad-schema"):
            core.validate_request(old, now=2_000_000_000)

    def test_package_is_content_addressed_and_tamper_evident(self):
        verified = package_v2.verify(self.package, self.evidence["manifest_sha256"], allowed_uid=None)
        self.assertEqual(verified["members"]["runtime/ollama"]["sha256"], self.runtime_hash)
        (self.package / "runtime/ollama").chmod(0o644)
        (self.package / "runtime/ollama").write_bytes(b"tamper")
        with self.assertRaises(package_v2.PackageRejected):
            package_v2.verify(self.package, self.evidence["manifest_sha256"], allowed_uid=None)

    def test_install_uninstall_and_every_publication_crash_are_clean(self):
        for phase in (None, "stage", "copy", "library", "launcher", "state", "policy"):
            fixture = self.root / ("fixture-" + (phase or "success"))
            fixture.mkdir()
            if phase is None:
                result = package_v2.rehearse(self.package, self.evidence["manifest_sha256"], fixture)
                self.assertTrue(result["ok"])
                self.assertTrue((fixture / core.NEW_BINARY.removeprefix("/")).is_file())
                # Synthetic uninstall removes authority/code and leaves no service effect.
                for rel in ("etc/sudoers.d/hermes-privileged-broker", "usr/local/sbin/hermes-privileged-broker",
                            "usr/local/lib/hermes-privileged-broker", "var/lib/hermes-privileged-broker"):
                    path = fixture / rel
                    if path.is_dir() and not path.is_symlink():
                        import os, shutil
                        for directory, directories, _ in os.walk(path):
                            Path(directory).chmod(0o700)
                            for child in directories: (Path(directory) / child).chmod(0o700)
                        shutil.rmtree(path)
                    else: path.unlink(missing_ok=True)
            else:
                with self.assertRaisesRegex(package_v2.PackageRejected, "injected"):
                    package_v2.rehearse(self.package, self.evidence["manifest_sha256"], fixture, phase)
                self.assertFalse((fixture / "usr/local/lib/hermes-privileged-broker").exists())
                self.assertFalse((fixture / "usr/local/sbin/hermes-privileged-broker").exists())
                self.assertFalse((fixture / "etc/sudoers.d/hermes-privileged-broker").exists())
                self.assertFalse((fixture / "var/lib/hermes-privileged-broker").exists())

    def test_request_binds_package_and_installed_runtime(self):
        package = core.sealed_package(str(self.package), self.evidence["manifest_sha256"])
        req = core.make_request("t_v2", 2, "R" * 32, 2_000_000_000, package=package)
        self.assertEqual(req["fixed_operation"]["executable"], core.NEW_BINARY)
        self.assertEqual(req["sealed_package"]["runtime_sha256"], self.runtime_hash)
        changed = dict(req); changed["sealed_package"] = dict(package); changed["sealed_package"]["manifest_sha256"] = "0" * 64
        core.validate_request(changed, now=2_000_000_000)
        self.assertNotEqual(core.digest(req), core.digest(changed))


if __name__ == "__main__": unittest.main()