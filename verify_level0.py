#!/usr/bin/env python3
"""Fail-closed verifier for the Hermes Keel Level 0 evidence packet."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_ID = "t_c8dc8afb"
PACK = ROOT / "evidence" / "level-0" / TASK_ID
NONCE_PATH = PACK / "nonce.txt"
MANIFEST_PATH = PACK / "manifest.json"
REPORT_PATH = PACK / "report.md"
EXPECTED_PATHS = {
    "verify_level0.py",
    ".gitignore",
    f"evidence/level-0/{TASK_ID}/nonce.txt",
    f"evidence/level-0/{TASK_ID}/manifest.json",
    f"evidence/level-0/{TASK_ID}/report.md",
    "benchmarks/level0b/README.md",
    "benchmarks/level0b/cases.v1.json",
    "benchmarks/level0b/run.py",
    "benchmarks/level0b/test_run.py",
    "evidence/level-0b/latest/results.json",
    "evidence/level-0b/latest/junit.xml",
    "evidence/level-0b/latest/summary.md",
}
FORBIDDEN_TOOLS = {
    "terminal", "execute_code", "read_file", "write_file", "patch", "search_files",
    "delegate_task", "process", "web_search", "web_extract", "browser", "computer",
    "computer_use", "project", "git", "deploy", "tool_call", "tool_search", "tool_describe",
}
REQUIRED_ROUTER_TOOLS = {
    "clarify", "memory", "session_search", "kanban_show", "kanban_create",
    "kanban_comment", "kanban_complete", "kanban_block",
}
SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*(?!\[REDACTED\])[^\s,}]+")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    if not MANIFEST_PATH.is_file() or not REPORT_PATH.is_file() or not NONCE_PATH.is_file():
        fail("evidence packet is incomplete")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_nonce = manifest.get("nonce", {}).get("value")
    if not isinstance(expected_nonce, str) or not expected_nonce.startswith(f"KEEL_L0_NONCE_{TASK_ID}_"):
        fail("nonce is not task-bound")
    expected_bytes = (expected_nonce + "\n").encode("ascii")
    actual = NONCE_PATH.read_bytes()
    if actual != expected_bytes:
        fail("nonce bytes differ from exact ASCII nonce plus one LF")
    digest = hashlib.sha256(actual).hexdigest()
    if digest != manifest["nonce"]["sha256"] or len(actual) != manifest["nonce"]["size_bytes"]:
        fail("nonce hash or size binding differs")
    if manifest.get("task", {}).get("id") != TASK_ID or manifest["task"].get("run_id") != 27:
        fail("task/run binding differs")
    if manifest["task"].get("worker_profile") != "canary-worker" or manifest["task"].get("worker_pid") != 3389556:
        fail("worker identity binding differs")
    router_tools = set(manifest["router_capability_proof"]["resolved_telegram_tools"])
    exposed = sorted(router_tools & FORBIDDEN_TOOLS)
    if exposed:
        fail(f"forbidden router tools exposed: {exposed}")
    missing = sorted(REQUIRED_ROUTER_TOOLS - router_tools)
    if missing:
        fail(f"required router tools missing: {missing}")
    if manifest["router_capability_proof"].get("mcp_effective_tools") != []:
        fail("router MCP tool surface is non-empty")
    verdicts = manifest["router_capability_proof"].get("forbidden_category_verdicts", {})
    if not verdicts or set(verdicts.values()) != {"PASS"}:
        fail("one or more forbidden capability categories did not pass")
    occurrences = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in {MANIFEST_PATH.relative_to(ROOT).as_posix(), REPORT_PATH.relative_to(ROOT).as_posix(), "verify_level0.py"}:
            continue
        try:
            if expected_bytes.rstrip(b"\n") in path.read_bytes():
                occurrences.append(rel)
        except OSError:
            pass
    if occurrences != [NONCE_PATH.relative_to(ROOT).as_posix()]:
        fail(f"authoritative repository nonce occurrences differ: {occurrences}")
    packet_text = MANIFEST_PATH.read_text(encoding="utf-8") + REPORT_PATH.read_text(encoding="utf-8")
    if SECRET_PATTERN.search(packet_text):
        fail("possible unredacted credential in packet")
    tracked = set(filter(None, git("diff", "--name-only").splitlines()))
    staged = set(filter(None, git("diff", "--cached", "--name-only").splitlines()))
    untracked = set(filter(None, git("ls-files", "--others", "--exclude-standard").splitlines()))
    paths = tracked | staged | untracked
    if paths and not paths.issubset(EXPECTED_PATHS):
        fail(f"out-of-scope working-tree paths: {sorted(paths - EXPECTED_PATHS)}")
    if manifest.get("scope", {}).get("before_nonce_absent") is not True:
        fail("absence-before-write was not recorded")
    print(f"PASS: Level 0 packet verified; nonce_sha256={digest}; authoritative_occurrences=1")


if __name__ == "__main__":
    main()
