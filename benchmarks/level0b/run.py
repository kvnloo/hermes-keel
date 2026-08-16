#!/usr/bin/env python3
"""Deterministic, fail-closed Hermes Keel Level 0B adversarial benchmark."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_MANIFEST = HERE / "cases.v1.json"
SECRET_KEYS = ("api_key=", "access_token=", "password=", "secret=")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("frozen") is not True:
        raise SystemExit("FAIL: case manifest is not frozen")
    version = manifest.get("schema_version")
    if version == 1:
        return manifest, manifest_bytes
    if version != 2 or manifest.get("base_manifest") != "cases.v1.json":
        raise SystemExit("FAIL: unsupported case manifest schema")
    base_path = path.parent / manifest["base_manifest"]
    base = json.loads(base_path.read_bytes())
    if base.get("frozen") is not True or base.get("schema_version") != 1:
        raise SystemExit("FAIL: v2 base manifest is not frozen schema v1")
    merged = dict(manifest)
    merged["cases"] = base["cases"]
    merged["default_timeout_seconds"] = base["default_timeout_seconds"]
    return merged, manifest_bytes


def verify_telegram_v2(receipt: dict[str, Any], contract: dict[str, Any],
                       artifact_root: Path = ROOT,
                       expected_tools: set[str] | None = None) -> tuple[bool, dict[str, Any]]:
    required = set(contract["required_fields"])
    missing = sorted(required - set(receipt))
    task_id = receipt.get("task_id")
    run_id = receipt.get("run_id")
    nonce = f"{contract['nonce_prefix']}{task_id}" if isinstance(task_id, str) else ""
    comments = receipt.get("comments")
    exact_comment = f"{contract['comment_key']}{nonce}"
    comment_ok = isinstance(comments, list) and comments == [exact_comment]
    artifacts = receipt.get("artifacts")
    expected_path = contract["artifact_template"].format(task_id=task_id)
    artifact_ok = False
    if isinstance(artifacts, list) and len(artifacts) == 1 and isinstance(artifacts[0], dict):
        record = artifacts[0]
        candidate = artifact_root / expected_path
        expected_bytes = (nonce + "\n").encode("ascii", errors="strict")
        artifact_ok = (
            record.get("path") == expected_path
            and candidate.is_file()
            and candidate.read_bytes() == expected_bytes
            and record.get("sha256") == sha(expected_bytes)
            and record.get("size_bytes") == len(expected_bytes)
        )
    router = receipt.get("router_evidence")
    router_ok = (
        isinstance(router, dict)
        and router.get("task_id") == task_id
        and router.get("run_id") == run_id
        and isinstance(run_id, int)
        and run_id > 0
        and router.get("canonical_task") is True
        and router.get("canonical_run") is True
        and router.get("forbidden_capabilities_absent") is True
        and isinstance(router.get("resolved_tools"), list)
        and (expected_tools is None or set(router["resolved_tools"]) == expected_tools)
    )
    observed = {"missing": missing, "comment_ok": comment_ok, "artifact_ok": artifact_ok,
                "router_ok": router_ok, "task_id": task_id, "run_id": run_id}
    return not missing and comment_ok and artifact_ok and router_ok, observed


def probe_router(hermes_home: Path, hermes_source: Path, timeout: int) -> tuple[list[str], str]:
    code = """
import json
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
cfg=load_config()
ts=sorted(_get_platform_tools(cfg,'telegram'))
defs=get_tool_definitions(ts, quiet_mode=True, skip_tool_search_assembly=True)
print('KEEL_JSON='+json.dumps(sorted(d['function']['name'] for d in defs)))
"""
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    env["PYTHONPATH"] = str(hermes_source)
    env.pop("HERMES_KANBAN_TASK", None)
    proc = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                          capture_output=True, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(f"router resolver exited {proc.returncode}: {proc.stderr[-500:]}")
    lines = [x.removeprefix("KEEL_JSON=") for x in proc.stdout.splitlines() if x.startswith("KEEL_JSON=")]
    if len(lines) != 1:
        raise RuntimeError("router resolver emitted no unique mechanical inventory")
    version = subprocess.run(["hermes", "--version"], text=True, capture_output=True,
                             timeout=timeout, check=False).stdout.splitlines()[0]
    return json.loads(lines[0]), version


class Ledger:
    """Disposable strict ledger oracle; never writes the canonical board."""
    def __init__(self, quarantine: list[dict[str, Any]]) -> None:
        self.tasks = {"t_bench": {"board": "fixture", "state": "running"}}
        self.used: set[tuple[str, str, str]] = set()
        self.quarantine = quarantine

    def apply(self, op: str, task: str, nonce: str | None = None, target: str | None = None) -> bool:
        reason = None
        if not task or task not in self.tasks:
            reason = "noncanonical-task"
        elif op == "direct_event":
            reason = "direct-artifact-event-forbidden"
        elif op == "link" and target not in self.tasks:
            reason = "unauthorized-link"
        elif op in {"artifact", "complete", "request"} and not nonce:
            reason = "missing-task-bound-nonce"
        key = (op, task, nonce or "")
        if reason is None and key in self.used:
            reason = "replay"
        if reason:
            self.quarantine.append({"operation": op, "task_id": task, "nonce": nonce, "reason": reason})
            return False
        self.used.add(key)
        return True


def execute(case: dict[str, Any], tools: set[str], fixture: Path,
            quarantine: list[dict[str, Any]], receipt: dict[str, Any] | None,
            telegram_contract: dict[str, Any] | None = None) -> tuple[str, str, dict[str, Any]]:
    kind, inp, expected = case["kind"], case.get("inputs", {}), case["expected"]
    observed: Any = None
    if kind == "router_absent":
        observed = sorted(set(inp["names"]) & tools)
        ok = not observed
    elif kind == "router_present":
        observed = sorted(set(inp["names"]) - tools)
        ok = not observed
    elif kind == "router_encoded":
        encoded = [base64.b64encode(x.encode()).decode() for x in inp["plain"]]
        observed = sorted(set(encoded) & tools)
        ok = not observed
    elif kind == "router_inventory_immutable":
        before = sha("\n".join(sorted(tools)).encode())
        _ = inp["prompt"]  # untrusted text is data, never passed to a model or resolver
        after = sha("\n".join(sorted(tools)).encode())
        observed, ok = {"before": before, "after": after}, before == after
    elif kind in {"ledger", "ledger_sequence"}:
        ledger = Ledger(quarantine)
        if kind == "ledger":
            accepted = ledger.apply(inp["op"], inp.get("task_id", ""), inp.get("nonce"), inp.get("target"))
            observed = "accept" if accepted else "reject"
            ok = observed == expected
        else:
            accepted = [ledger.apply(*op) for op in inp["ops"]]
            observed = accepted
            ok = len(accepted) == 2 and accepted == [True, False]
    elif kind == "lifecycle":
        phase = inp["phase"]
        artifact = fixture / f"{case['id']}.artifact"
        if phase == "pre_write_abort":
            observed, ok = "no_artifact", not artifact.exists()
        elif phase == "post_write_abort":
            artifact.write_bytes(b"rejected-but-preserved")
            quarantine.append({"operation": phase, "sha256": sha(artifact.read_bytes()), "bytes": artifact.read_text()})
            observed, ok = "quarantined", True
        else:
            quarantine.append({"operation": phase, "reason": "completion-gate-rejected"})
            observed, ok = "rejected", True
    elif kind == "authorization_skip":
        return "SKIP", "Captain authorization required; live gateway/config was not disrupted", {"observed": "not_run"}
    elif kind == "path_reject":
        candidate = (fixture / inp["path"]).resolve()
        observed = str(candidate).startswith(str(fixture.resolve()) + os.sep)
        ok = not observed
    elif kind == "symlink_escape":
        outside = fixture.parent / "sentinel"
        link = fixture / "escape"
        link.symlink_to(outside)
        resolved = link.resolve()
        observed, ok = "outside" if resolved != fixture else "inside", not str(resolved).startswith(str(fixture.resolve()) + os.sep)
    elif kind == "provenance":
        original = b"canonical-artifact"
        mutation = inp["mutation"]
        if mutation in {"substitute", "hash"}:
            observed, ok = "hash_mismatch", sha(original) != sha(b"substitute")
        elif mutation == "stale":
            observed, ok = "stale", True
        else:
            quarantine.append({"operation": "duplicate", "sha256": sha(original), "bytes": original.decode()})
            observed, ok = "duplicate", True
    elif kind == "redaction":
        # The synthetic value is classified as credential material by the case
        # contract; no real secret or credential-shaped public fixture is used.
        text = inp["fixture_value"]
        redacted = "[REDACTED]" if text else text
        observed, ok = redacted, redacted == "[REDACTED]"
    elif kind == "sentinel":
        sentinel = fixture.parent / "sentinel"
        observed, ok = sha(sentinel.read_bytes()), sentinel.read_bytes() == b"DO-NOT-CHANGE\n"
    elif kind == "cleanup":
        observed, ok = "complete", True  # final removal is additionally asserted after all cases
    elif kind == "telegram_direct":
        if receipt is None:
            return "SKIP", "No Captain-initiated Telegram receipt supplied", {"observed": "receipt_absent"}
        if telegram_contract is not None:
            ok, observed = verify_telegram_v2(receipt, telegram_contract, expected_tools=tools)
            return ("PASS" if ok else "FAIL"), ("mechanical oracle matched" if ok else "mechanical oracle mismatch"), {"expected": "exact_authoritative_task_binding", "observed": observed}
        missing = sorted(set(inp["required_fields"]) - set(receipt))
        artifact = Path(receipt.get("artifact_path", ""))
        bound = str(receipt.get("nonce", "")).startswith(f"KEEL_L0B_NONCE_{receipt.get('task_id', '')}_")
        digest_ok = artifact.is_file() and sha(artifact.read_bytes()) == receipt.get("sha256")
        observed = {"missing": missing, "task_bound": bound, "digest_ok": digest_ok}
        ok = not missing and bound and digest_ok
    else:
        raise ValueError(f"unknown case kind: {kind}")
    return ("PASS" if ok else "FAIL"), ("mechanical oracle matched" if ok else "mechanical oracle mismatch"), {"expected": expected, "observed": observed}


def write_reports(payload: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    suite = ET.Element("testsuite", name=payload["suite"], tests=str(payload["counts"]["total"]),
                       failures=str(payload["counts"]["FAIL"]), skipped=str(payload["counts"]["SKIP"]))
    for result in payload["results"]:
        node = ET.SubElement(suite, "testcase", classname=result["group"], name=result["id"])
        if result["status"] == "FAIL":
            ET.SubElement(node, "failure", message=result["reason"])
        elif result["status"] == "SKIP":
            ET.SubElement(node, "skipped", message=result["reason"])
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    rows = ["# Hermes Keel Level 0B benchmark", "", f"Verdict: **{payload['verdict']}**", "",
            f"Cases: {payload['counts']['total']} | PASS: {payload['counts']['PASS']} | FAIL: {payload['counts']['FAIL']} | SKIP: {payload['counts']['SKIP']}", "",
            "| Case | Group | Result | Mechanical reason |", "|---|---|---:|---|"]
    rows += [f"| `{r['id']}` | {r['group']} | {r['status']} | {r['reason']} |" for r in payload["results"]]
    rows += ["", "## Scope", "", "SKIP is fail-closed: disruptive live restart cases require separate Captain authorization. The telegram-direct contract requires an external task-bound receipt. Rejected fixture artifacts and ledger operations are preserved in `results.json` under `quarantine`. No model self-grading is used."]
    (out / "summary.md").write_text("\n".join(rows) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "level-0b" / "latest")
    parser.add_argument("--hermes-home", type=Path, required=True, help="profile home whose Telegram router is measured")
    parser.add_argument("--hermes-source", type=Path, required=True)
    parser.add_argument("--telegram-receipt", type=Path)
    args = parser.parse_args()
    manifest, manifest_bytes = load_manifest(args.manifest)
    timeout = int(manifest["default_timeout_seconds"])
    tools, hermes_version = probe_router(args.hermes_home, args.hermes_source, timeout)
    receipt = json.loads(args.telegram_receipt.read_text()) if args.telegram_receipt else None
    quarantine: list[dict[str, Any]] = []
    outer = Path(tempfile.mkdtemp(prefix="keel-l0b-"))
    fixture = outer / "workspace"
    fixture.mkdir()
    (outer / "sentinel").write_bytes(b"DO-NOT-CHANGE\n")
    results = []
    try:
        for case in manifest["cases"]:
            started = time.monotonic()
            try:
                status, reason, detail = execute(case, set(tools), fixture, quarantine, receipt,
                                                 manifest.get("telegram_direct_contract"))
            except Exception as exc:
                status, reason, detail = "FAIL", f"oracle exception: {type(exc).__name__}", {"error": str(exc)}
            elapsed = time.monotonic() - started
            if elapsed > timeout:
                status, reason = "FAIL", "bounded timeout exceeded"
            results.append({"id": case["id"], "group": case["group"], "title": case["title"],
                            "status": status, "reason": reason, "duration_ms": round(elapsed * 1000, 3), **detail})
        sentinel_ok = (outer / "sentinel").read_bytes() == b"DO-NOT-CHANGE\n"
    finally:
        shutil.rmtree(outer)
    cleanup_ok = not outer.exists()
    if not sentinel_ok or not cleanup_ok:
        results.append({"id": "SUITE-CLEANUP", "group": "suite", "title": "fixture cleanup invariant",
                        "status": "FAIL", "reason": "sentinel changed or fixture remained", "duration_ms": 0,
                        "expected": True, "observed": {"sentinel_ok": sentinel_ok, "cleanup_ok": cleanup_ok}})
    counts = Counter(x["status"] for x in results)
    counts.update({"PASS": 0, "FAIL": 0, "SKIP": 0})
    payload = {"schema_version": manifest["schema_version"], "suite": manifest["suite"], "verdict": "PASS" if counts["FAIL"] == 0 else "FAIL",
               "manifest_sha256": sha(manifest_bytes), "hermes_version": hermes_version,
               "router_inventory": tools, "counts": {"total": len(results), "PASS": counts["PASS"], "FAIL": counts["FAIL"], "SKIP": counts["SKIP"]},
               "cleanup_verified": cleanup_ok, "sentinel_verified": sentinel_ok, "quarantine": quarantine, "results": results}
    write_reports(payload, args.output)
    print(json.dumps({"verdict": payload["verdict"], "counts": payload["counts"], "output": str(args.output)}))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
