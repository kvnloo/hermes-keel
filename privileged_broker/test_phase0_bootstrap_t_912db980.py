import json
import os
import shutil
import sqlite3
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
MANIFEST_SHA256 = "c74d21bd4f3204ae16c9d7c4e53a420ce15e58ef0e16bdeecf45ffd7a6827aec"


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
        self.board = self.base / "board.db"
        db=sqlite3.connect(self.board)
        db.executescript("create table tasks(id text,status text,completed_at int,block_kind text,body text,current_run_id int);"
                         "create table task_runs(id int,task_id text,status text,ended_at int,outcome text);"
                         "create table task_comments(task_id text,body text);")
        self.binding = self.base / "binding.json"
        self.binding_body={"schema":"keel.phase0-binding.v1","task":"t_phase0","run":912,
              "board":str(self.board),"board_identity":{},"host":"groot","source":str(self.source),
              "manifest_sha256":MANIFEST_SHA256,"action":"ollama-system-runtime-switch-v2",
              "nonce":"N"*40,"created_at":__import__('time').time_ns()//1_000_000_000,
              "expires_at":__import__('time').time_ns()//1_000_000_000+1800}
        packet_hash=self.write_binding()
        db.execute("insert into tasks values(?,?,?,?,?,?)",("t_phase0","running",None,None,packet_hash,912))
        db.execute("insert into task_runs values(?,?,?,?,?)",(912,"t_phase0","running",None,None)); db.commit(); db.close()
        self.pre = self.base / "pre.json"; self.pre.write_text(json.dumps(core.fixture_pre_state()))

    def tearDown(self): self.temp.cleanup()

    def write_binding(self, **changes):
        body={**self.binding_body, **changes}
        packet_hash=__import__('hashlib').sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
        packet={**body,"packet_sha256":packet_hash}
        if self.binding.exists(): self.binding.chmod(0o644)
        self.binding.write_text(json.dumps(packet)); self.binding.chmod(0o444)
        return packet_hash

    def invoke(self, fail=None, extra=None, argv=()):
        env={**os.environ,"KEEL_PHASE0_ROOTLESS_FIXTURE":"1","KEEL_PHASE0_BINDING":str(self.binding),
             "KEEL_PHASE0_TRUSTED_ROOT":str(self.trusted),"KEEL_PHASE0_INSTALL_ROOT":str(self.root),
             "KEEL_PHASE0_PRESTATE":str(self.pre)}
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
        self.assertNotIn("systemctl",text); self.assertNotIn(" approve(",text); self.assertNotIn("from core import execute",text)
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

    def test_binding_tamper_expiry_substitution_and_historical_run_reject_clean(self):
        original=self.binding.read_bytes()
        cases=(
            ("hash-tamper", lambda: self.binding.write_bytes(original.replace(b'"host": "groot"',b'"host": "other"'))),
            ("expired", lambda: self.write_binding(created_at=1,expires_at=2)),
            ("future", lambda: self.write_binding(created_at=4_000_000_000,expires_at=4_000_000_100)),
            ("source-substitution", lambda: self.write_binding(source="relative/package")),
            ("run-substitution", lambda: self.write_binding(run=913)),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                self.binding.chmod(0o644); mutate(); self.binding.chmod(0o444)
                cp=self.invoke(); self.assertNotEqual(cp.returncode,0,cp.stdout+cp.stderr)
                self.assert_clean()
                self.binding.chmod(0o644); self.binding.write_bytes(original); self.binding.chmod(0o444)

        real=self.base/"binding-real.json"
        real.write_bytes(original); self.binding.unlink(); self.binding.symlink_to(real)
        cp=self.invoke(); self.assertNotEqual(cp.returncode,0); self.assert_clean()

    def test_phase1_accepts_only_live_successor_of_needs_input_gate(self):
        request_hash="a"*64
        db=sqlite3.connect(self.board)
        db.execute("update tasks set status='running',block_kind='needs_input',body=?,current_run_id=913 where id='t_phase0'",(request_hash,))
        db.execute("update task_runs set status='blocked',ended_at=1,outcome='blocked' where id=912")
        db.execute("insert into task_runs values(?,?,?,?,?)",(913,"t_phase0","running",None,None)); db.commit()
        core._task_active_connection(db,"t_phase0",912,request_hash)
        mutations=(
            "update tasks set status='ready' where id='t_phase0'",
            "update tasks set block_kind='capability' where id='t_phase0'",
            "update task_runs set ended_at=2,outcome='completed',status='done' where id=913",
        )
        for mutation in mutations:
            db.execute(mutation); db.commit()
            with self.assertRaisesRegex(core.Rejected,"inactive-task-run"):
                core._task_active_connection(db,"t_phase0",912,request_hash)
            db.execute("update tasks set status='running',block_kind='needs_input' where id='t_phase0'")
            db.execute("update task_runs set ended_at=null,outcome=null,status='running' where id=913")
            db.commit()
        db.close()


if __name__ == "__main__": unittest.main()
