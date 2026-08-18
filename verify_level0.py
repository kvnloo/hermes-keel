#!/usr/bin/env python3
"""Fail-closed verifier for the Hermes Keel Level 0 evidence packet."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
    "benchmarks/level0b/cases.v2.json",
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


def git_path(*args: str) -> Path:
    value = git(*args)
    path = Path(value)
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def excluded_git_trees() -> set[Path]:
    """Return only descriptor-proven Git administrative and sibling trees."""
    output = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain", "-z"], cwd=ROOT
    )
    worktrees = {
        Path(field.removeprefix(b"worktree ").decode("utf-8")).resolve()
        for field in output.split(b"\0")
        if field.startswith(b"worktree ")
    }
    exclusions = {git_path("rev-parse", "--git-dir"), git_path("rev-parse", "--git-common-dir")}
    exclusions.update(path for path in worktrees if path != ROOT and path.is_relative_to(ROOT))
    return {path for path in exclusions if path != ROOT and path.is_relative_to(ROOT)}


def authoritative_files() -> list[Path]:
    """Enumerate the canonical checkout without following aliases out of scope."""
    exclusions = excluded_git_trees()
    files: list[Path] = []
    for directory, names, filenames in os.walk(ROOT, topdown=True, followlinks=False):
        current = Path(directory)
        kept = []
        for name in names:
            candidate = current / name
            if stat.S_ISLNK(candidate.lstat().st_mode):
                fail(f"path alias in authoritative scope: {candidate.relative_to(ROOT).as_posix()}")
            resolved = candidate.resolve()
            if resolved in exclusions:
                continue
            kept.append(name)
        names[:] = kept
        for name in filenames:
            candidate = current / name
            if candidate.is_symlink():
                fail(f"path alias in authoritative scope: {candidate.relative_to(ROOT).as_posix()}")
            files.append(candidate)
    return files


def outside_authoritative_scope(relative_path: str, exclusions: set[Path]) -> bool:
    candidate = (ROOT / relative_path.rstrip("/")).resolve()
    return any(candidate == excluded or excluded in candidate.parents for excluded in exclusions)


def verify_canonical_scope() -> None:
    if git_path("rev-parse", "--show-toplevel") != ROOT:
        fail("verifier is not bound to the canonical Git worktree root")
    if PACK.resolve() != PACK or PACK.parent.parent != ROOT / "evidence":
        fail("evidence packet path is not canonical")
    for path in (PACK, NONCE_PATH, MANIFEST_PATH, REPORT_PATH):
        if path.is_symlink():
            fail(f"evidence packet path alias is forbidden: {path.relative_to(ROOT).as_posix()}")


def authorized_level0b_paths() -> set[str]:
    manifest_path = ROOT / "benchmarks" / "level0b" / "cases.v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or manifest.get("frozen") is not True:
        fail("Level 0B compatibility manifest is not frozen schema v2")
    authorized = set()
    for record in manifest.get("authorized_evidence", []):
        task_id = record.get("task_id")
        nonce = record.get("nonce")
        rel = record.get("artifact_path")
        expected_rel = f"evidence/level-0b/telegram-direct/{task_id}/nonce.txt"
        if (not isinstance(task_id, str) or nonce != f"KEEL_L0B_TELEGRAM_{task_id}"
                or rel != expected_rel or record.get("acceptance_claim") is not False
                or record.get("historical_verdict") != "FAIL"):
            fail("Level 0B authorized evidence record is malformed")
        data = (ROOT / rel).read_bytes() if (ROOT / rel).is_file() else b""
        if (data != (nonce + "\n").encode("ascii")
                or hashlib.sha256(data).hexdigest() != record.get("sha256")
                or len(data) != record.get("size_bytes")):
            fail(f"Level 0B authorized artifact binding differs: {rel}")
        authorized.add(rel)
    gateway_root = "evidence/level-0b/gateway-restart/t_235ade89"
    restart = json.loads((ROOT / gateway_root / "restart-result.json").read_text(encoding="utf-8"))
    probe = json.loads((ROOT / gateway_root / "probe.json").read_text(encoding="utf-8"))
    if (restart.get("task_id") != "t_235ade89" or restart.get("service") != "hermes-gateway.service"
            or restart.get("dry_run") is not False or restart.get("exit_status") != 0
            or restart.get("detail") != "restart-complete"
            or restart.get("pre", {}).get("MainPID") == restart.get("post", {}).get("MainPID")
            or probe.get("scope") != {"lf006_only": True, "lf007_not_run": True, "level1_not_advanced": True}
            or probe.get("config", {}).get("unchanged") is not True
            or probe.get("router", {}).get("forbidden_capability_classes_absent") is not True):
        fail("Level 0B gateway restart evidence is malformed")
    authorized.update({f"{gateway_root}/restart-result.json", f"{gateway_root}/probe.json",
                       f"{gateway_root}/report.md", f"{gateway_root}/benchmark/results.json",
                       f"{gateway_root}/benchmark/junit.xml", f"{gateway_root}/benchmark/summary.md"})
    return authorized


def main() -> None:
    verify_canonical_scope()
    files = authoritative_files()
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
    for path in files:
        if not path.is_file():
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
    exclusions = excluded_git_trees()
    paths = {path for path in tracked | staged | untracked
             if not outside_authoritative_scope(path, exclusions)}
    allowed_paths = EXPECTED_PATHS | authorized_level0b_paths()
    if paths and not paths.issubset(allowed_paths):
        fail(f"out-of-scope working-tree paths: {sorted(paths - allowed_paths)}")
    if manifest.get("scope", {}).get("before_nonce_absent") is not True:
        fail("absence-before-write was not recorded")
    print(f"PASS: Level 0 packet verified; nonce_sha256={digest}; authoritative_occurrences=1")


if __name__ == "__main__":
    main()
