import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from privileged_broker import core
from privileged_broker import phase0_bootstrap

SCRIPT = Path(__file__).with_name("phase0_bootstrap.py")
SOURCE = Path("/var/tmp/hermes-keel-phase0-package-t_912db980-r186")


class Phase0ActualScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        shutil.copytree(SOURCE, self.source)
        for p in self.source.rglob("*"):
            if p.is_dir(): p.chmod(0o555)
            else: p.chmod(0o444)
        self.source.chmod(0o555)
        self.root = self.base / "root"
        for rel, mode in (("usr/local/lib",0o755),("usr/local/sbin",0o755),
                          ("etc/sudoers.d",0o750),("var/lib",0o755),("var/tmp",0o1777)):
            p=self.root/rel; p.mkdir(parents=True,exist_ok=True); p.chmod(mode)
        self.trusted = self.base / "root-private" / "ceremony"
        (self.base / "root-private").mkdir(mode=0o700)
        self.board = self.base / "board.db"; self.board.write_bytes(b"fixture")
        self.pre = self.base / "pre.json"; self.pre.write_text(json.dumps(core.fixture_pre_state()))

    def tearDown(self): self.temp.cleanup()

    def invoke(self, fail=None, extra=None, argv=()):
        env={**os.environ,"KEEL_PHASE0_ROOTLESS_FIXTURE":"1","KEEL_PHASE0_SOURCE":str(self.source),
             "KEEL_PHASE0_TRUSTED_ROOT":str(self.trusted),"KEEL_PHASE0_INSTALL_ROOT":str(self.root),
             "KEEL_PHASE0_BOARD":str(self.board),"KEEL_PHASE0_PRESTATE":str(self.pre),
             "KEEL_PHASE0_TASK":"t_phase0","KEEL_PHASE0_RUN":"912"}
        if fail: env["KEEL_PHASE0_FAIL_AFTER"]=fail
        if extra: env.update(extra)
        return subprocess.run([sys.executable,str(SCRIPT),*argv],env=env,capture_output=True,text=True)

    def assert_clean(self):
        for rel in ("usr/local/lib/hermes-privileged-broker","usr/local/sbin/hermes-privileged-broker",
                    "etc/sudoers.d/hermes-privileged-broker","var/lib/hermes-privileged-broker"):
            self.assertFalse((self.root/rel).exists(),rel)
        self.assertFalse(self.trusted.exists())

    def test_actual_script_failure_cleanup_before_and_after_install(self):
        for phase in ("sealed-copy","trusted-publication","installed"):
            with self.subTest(phase=phase):
                cp=self.invoke(phase); self.assertNotEqual(cp.returncode,0,cp.stdout+cp.stderr)
                self.assert_clean()

    def test_success_restart_idempotency_and_receipts(self):
        first=self.invoke(); self.assertEqual(first.returncode,0,first.stderr)
        request=self.root/"var/lib/hermes-privileged-broker/requests/phase1-ollama-system-runtime-switch-v2.json"
        receipt=self.root/"var/lib/hermes-privileged-broker/phase0-audit.json"
        before=request.read_bytes(); audit=json.loads(receipt.read_text())
        self.assertFalse(audit["effects"]["ollama_mutated"])
        self.assertFalse(audit["effects"]["authorization_consumed"])
        second=self.invoke(); self.assertEqual(second.returncode,0,second.stderr)
        self.assertIn("already complete",second.stdout)
        self.assertEqual(before,request.read_bytes())
        self.assertEqual(audit["request_sha256"],__import__("hashlib").sha256(before.rstrip(b"\n")).hexdigest())

    def test_tamper_v1_one_step_uid1000_and_arguments_reject(self):
        tampered=self.source/"core.py"; tampered.chmod(0o644); tampered.write_text("tamper")
        cp=self.invoke(); self.assertNotEqual(cp.returncode,0); self.assert_clean()
        text=SCRIPT.read_text()
        self.assertNotIn("systemctl",text); self.assertNotIn(" approve(",text); self.assertNotIn("execute(",text)
        self.assertNotIn("runtime-switch-v1",text)
        cp=subprocess.run([sys.executable,str(SCRIPT),"one-step"],capture_output=True,text=True)
        self.assertNotEqual(cp.returncode,0); self.assertIn("phase0-accepts-no-arguments",cp.stderr)

    def test_fixed_argv_rejects_before_fixture_or_production_selection(self):
        for fixture_value in ("1", "0", "", "unexpected"):
            for argv in (("positional",), ("--flag",), ("--flag=value", "extra")):
                with self.subTest(fixture=fixture_value, argv=argv):
                    cp = self.invoke(extra={"KEEL_PHASE0_ROOTLESS_FIXTURE": fixture_value}, argv=argv)
                    self.assertNotEqual(cp.returncode, 0)
                    self.assertEqual(cp.stdout, "")
                    self.assertIn("phase0-accepts-no-arguments", cp.stderr)
                    self.assert_clean()

        # Shape the production branch as root without requiring privilege.  A
        # hostile argv must be rejected before root/configuration or sealing.
        with (mock.patch.object(sys, "argv", [str(SCRIPT), "--hostile"]),
              mock.patch.object(phase0_bootstrap.os, "geteuid", return_value=0),
              mock.patch.object(phase0_bootstrap, "_seal") as seal):
            with self.assertRaisesRegex(phase0_bootstrap.Rejected,
                                        "phase0-accepts-no-arguments"):
                phase0_bootstrap._configuration()
            seal.assert_not_called()
        self.assert_clean()


if __name__ == "__main__": unittest.main()
