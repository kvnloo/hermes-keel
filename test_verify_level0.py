#!/usr/bin/env python3
"""Adversarial scope tests for the Level 0 verifier."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parent
NONCE_REL = Path("evidence/level-0/t_c8dc8afb/nonce.txt")


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


class VerifyLevel0ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="keel-k0-scope-"))
        self.repo = self.temp / "repo"
        run("git", "clone", "--quiet", str(SOURCE), str(self.repo), cwd=self.temp)
        shutil.copy2(SOURCE / "verify_level0.py", self.repo / "verify_level0.py")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def verify(self, root: Path | None = None) -> subprocess.CompletedProcess[str]:
        root = root or self.repo
        return run("python3", "verify_level0.py", cwd=root, check=False)

    def test_clean_clone_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_descriptor_known_sibling_duplicate_is_excluded(self) -> None:
        sibling = self.repo / "nested" / "sibling"
        sibling.parent.mkdir()
        run("git", "worktree", "add", "--quiet", "--detach", str(sibling), cwd=self.repo)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_duplicate_inside_authoritative_packet_fails(self) -> None:
        nonce = (self.repo / NONCE_REL).read_bytes()
        duplicate = self.repo / NONCE_REL.parent / "duplicate.txt"
        duplicate.write_bytes(nonce)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authoritative repository nonce occurrences differ", result.stdout + result.stderr)

    def test_unexpected_in_scope_artifact_fails(self) -> None:
        (self.repo / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("out-of-scope working-tree paths", result.stdout + result.stderr)

    def test_symlink_alias_cannot_escape_scope(self) -> None:
        foreign = self.temp / "foreign.txt"
        foreign.write_bytes((self.repo / NONCE_REL).read_bytes())
        os.symlink(foreign, self.repo / "nonce-alias.txt")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path alias in authoritative scope", result.stdout + result.stderr)

    def assert_directory_alias_fails(self, link: Path) -> None:
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"path alias in authoritative scope: {link.relative_to(self.repo).as_posix()}",
            result.stdout + result.stderr,
        )

    def test_descriptor_known_git_admin_alias_fails_before_exclusion(self) -> None:
        git_dir = Path(run("git", "rev-parse", "--git-dir", cwd=self.repo).stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.repo / git_dir
        alias = self.repo / "git-admin-alias"
        os.symlink(git_dir, alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_descriptor_known_sibling_alias_fails_before_exclusion(self) -> None:
        sibling = self.repo / "nested" / "sibling"
        sibling.parent.mkdir()
        run("git", "worktree", "add", "--quiet", "--detach", str(sibling), cwd=self.repo)
        alias = self.repo / "sibling-alias"
        os.symlink(sibling, alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_absolute_directory_alias_fails_without_target_read(self) -> None:
        target = self.temp / "absolute-target"
        target.mkdir()
        (target / "nonce.txt").write_bytes((self.repo / NONCE_REL).read_bytes())
        alias = self.repo / "absolute-alias"
        os.symlink(target, alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_relative_directory_alias_fails_without_target_read(self) -> None:
        target = self.temp / "relative-target"
        target.mkdir()
        (target / "nonce.txt").write_bytes((self.repo / NONCE_REL).read_bytes())
        alias = self.repo / "relative-alias"
        os.symlink(os.path.relpath(target, self.repo), alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_broken_directory_alias_fails_without_target_read(self) -> None:
        alias = self.repo / "broken-alias"
        os.symlink(self.temp / "missing-target", alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_loop_directory_alias_fails_without_target_resolution(self) -> None:
        alias = self.repo / "loop-alias"
        os.symlink(alias.name, alias, target_is_directory=True)
        self.assert_directory_alias_fails(alias)

    def test_unregistered_nested_checkout_is_not_implicitly_ignored(self) -> None:
        nested = self.repo / "nested-repository"
        nested.mkdir()
        (nested / "nonce.txt").write_bytes((self.repo / NONCE_REL).read_bytes())
        run("git", "init", "--quiet", cwd=nested)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authoritative repository nonce occurrences differ", result.stdout + result.stderr)

    def test_foreign_dirty_file_is_untouched(self) -> None:
        foreign = self.temp / "foreign-dirty.txt"
        foreign.write_text("do not touch\n", encoding="utf-8")
        before = foreign.read_bytes()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(foreign.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()