#!/usr/bin/env python3
import importlib.util
import hashlib
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

    def test_frozen_v1_and_failed_run_are_byte_reproducible(self):
        self.assertEqual("2d3a3613cd6f8681bb95d7182bb23ad935ffe6d97dbcc1b14cea493b791b7e49",
                         hashlib.sha256((HERE / "cases.v1.json").read_bytes()).hexdigest())
        results = json.loads((HERE.parents[1] / "evidence/level-0b/latest/results.json").read_text())
        td = next(result for result in results["results"] if result["id"] == "TD-001")
        self.assertEqual("SKIP", td["status"])
        case = next(case for case in json.loads((HERE / "cases.v1.json").read_text())["cases"] if case["id"] == "TD-001")
        receipt = {"task_id": "t_72294ce7", "nonce": "KEEL_L0B_TELEGRAM_t_72294ce7",
                   "artifact_path": str(HERE.parents[1] / "evidence/level-0b/telegram-direct/t_72294ce7/nonce.txt"),
                   "sha256": "d7a82860f5daae2f30008194f7eeeb5783dcbb2e7556b81ac5a084cf3d43ebb3"}
        status, _, _ = mod.execute(case, set(), Path("/tmp"), [], receipt)
        self.assertEqual("FAIL", status)

    def test_v2_telegram_contract_is_exact_and_fail_closed(self):
        manifest, _ = mod.load_manifest(HERE / "cases.v2.json")
        contract = manifest["telegram_direct_contract"]
        task_id = "t_contract"
        nonce = f"KEEL_L0B_TELEGRAM_{task_id}"
        rel = f"evidence/level-0b/telegram-direct/{task_id}/nonce.txt"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / rel
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes((nonce + "\n").encode())
            receipt = {
                "task_id": task_id, "run_id": 42,
                "comments": [f"EXACT_NONCE={nonce}"],
                "artifacts": [{"path": rel, "sha256": mod.sha(artifact.read_bytes()),
                               "size_bytes": len(artifact.read_bytes())}],
                "router_evidence": {"task_id": task_id, "run_id": 42, "canonical_task": True,
                                    "canonical_run": True, "forbidden_capabilities_absent": True,
                                    "resolved_tools": ["kanban_show"]},
            }
            self.assertTrue(mod.verify_telegram_v2(receipt, contract, root)[0])

            mutations = []
            wrong_task = json.loads(json.dumps(receipt)); wrong_task["task_id"] = "t_wrong"; mutations.append(wrong_task)
            extra_comment = json.loads(json.dumps(receipt)); extra_comment["comments"].append("EXACT_NONCE=extra"); mutations.append(extra_comment)
            alternate_prefix = json.loads(json.dumps(receipt)); alternate_prefix["comments"] = [f"EXACT_NONCE=KEEL_L0B_NONCE_{task_id}"]; mutations.append(alternate_prefix)
            suffix = json.loads(json.dumps(receipt)); suffix["comments"] = [f"EXACT_NONCE={nonce}_suffix"]; mutations.append(suffix)
            duplicate = json.loads(json.dumps(receipt)); duplicate["artifacts"].append(dict(duplicate["artifacts"][0])); mutations.append(duplicate)
            wrong_hash = json.loads(json.dumps(receipt)); wrong_hash["artifacts"][0]["sha256"] = "0" * 64; mutations.append(wrong_hash)
            missing_run = json.loads(json.dumps(receipt)); del missing_run["run_id"]; mutations.append(missing_run)
            for mutation in mutations:
                self.assertFalse(mod.verify_telegram_v2(mutation, contract, root)[0])

            artifact.write_bytes(b"wrong\n")
            self.assertFalse(mod.verify_telegram_v2(receipt, contract, root)[0])

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
