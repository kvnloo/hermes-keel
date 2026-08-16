#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("level0b", HERE / "run.py")
assert SPEC is not None
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class Level0BTests(unittest.TestCase):
    def test_manifest_is_frozen_and_case_ids_unique(self):
        data = json.loads((HERE / "cases.v1.json").read_text())
        self.assertTrue(data["frozen"])
        ids = [case["id"] for case in data["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({"router_escape", "canonical_ledger", "lifecycle_failure", "isolation_provenance", "telegram_direct"}, {case["group"] for case in data["cases"]})

    def test_ledger_rejects_replay_and_preserves_record(self):
        quarantine = []
        ledger = mod.Ledger(quarantine)
        self.assertTrue(ledger.apply("complete", "t_bench", "nonce-a"))
        self.assertFalse(ledger.apply("complete", "t_bench", "nonce-a"))
        self.assertEqual("replay", quarantine[0]["reason"])

    def test_ledger_rejects_orphan(self):
        quarantine = []
        self.assertFalse(mod.Ledger(quarantine).apply("artifact", "t_missing", "nonce-a"))
        self.assertEqual("noncanonical-task", quarantine[0]["reason"])

    def test_reports_are_machine_readable(self):
        payload = {"suite":"test", "verdict":"PASS", "counts":{"total":0,"PASS":0,"FAIL":0,"SKIP":0}, "results":[]}
        with tempfile.TemporaryDirectory() as tmp:
            mod.write_reports(payload, Path(tmp))
            json.loads((Path(tmp) / "results.json").read_text())
            self.assertTrue((Path(tmp) / "junit.xml").read_text().startswith("<?xml"))
            self.assertIn("Verdict: **PASS**", (Path(tmp) / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
