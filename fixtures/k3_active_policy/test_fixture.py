from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .fixture import DisposablePolicy, Frozen, OPERATIONS, sign, synthetic_body


NOW = 1_800_000_000
KEY = b"synthetic-key-never-installed"


class ActivePolicyFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.anchor = self.root / "anchor"
        self.anchor.write_text("synthetic anchor\n")
        self.body = synthetic_body(self.anchor, NOW)
        self.receipt = self.root / "active.json"
        self.db = self.root / "board.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, body=None, key=KEY):
        self.receipt.write_text(json.dumps(sign(self.body if body is None else body, key)))

    def policy(self, provider=lambda: KEY, expected=None, db=None):
        expected = dict(self.body) if expected is None else expected
        return DisposablePolicy(self.db if db is None else db, provider, expected)

    def assert_frozen(self, reason, action):
        with self.assertRaisesRegex(Frozen, reason):
            action()

    def test_green_active_snapshot_gates_all_dispatch_operations(self):
        self.write()
        policy = self.policy()
        snapshot = policy.load(self.receipt, NOW)
        boundary = snapshot.boundary()
        for operation in OPERATIONS:
            policy.dispatch(operation, boundary)
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute("SELECT operation,generation FROM mutations ORDER BY seq").fetchall()
        self.assertEqual(rows, [(operation, 7) for operation in OPERATIONS])

    def test_missing_active_denies_before_dispatch_mutation(self):
        policy = self.policy()
        self.assert_frozen("missing-or-malformed-active", lambda: policy.load(self.receipt, NOW))
        self.assert_frozen("active-snapshot-missing", lambda: policy.dispatch("create", {}))

    def test_unavailable_key_provider_denies(self):
        self.write()
        self.assert_frozen("key-provider-unavailable", lambda: self.policy(lambda: None).load(self.receipt, NOW))

    def test_effective_and_expiry_boundaries_fail_closed(self):
        cases = (
            ("active-not-yet-effective", {**self.body, "effective_at": NOW + 1}, NOW),
            ("active-expired", {**self.body, "expires_at": NOW}, NOW),
            ("active-expired", {**self.body, "expires_at": NOW - 1}, NOW),
        )
        for reason, body, current in cases:
            with self.subTest(reason=reason, body=body):
                self.write(body)
                self.assert_frozen(reason, lambda: self.policy(expected=body).load(self.receipt, current))

        for body in (
            {**self.body, "effective_at": NOW},
            {**self.body, "expires_at": NOW + 1},
        ):
            with self.subTest(valid_boundary=body):
                self.write(body)
                self.policy(expected=body, db=self.root / f"valid-{body['expires_at']}.sqlite3").load(
                    self.receipt, NOW
                )

    def test_replayed_nonce_denies_across_startups(self):
        self.write()
        self.policy().load(self.receipt, NOW)
        self.assert_frozen("active-replayed", lambda: self.policy().load(self.receipt, NOW))

    def test_mac_and_inactive_receipts_deny(self):
        self.write(key=b"wrong-key")
        self.assert_frozen("receipt-mac-mismatch", lambda: self.policy().load(self.receipt, NOW))
        body = {**self.body, "status": "FROZEN"}
        self.write(body)
        self.assert_frozen("active-required", lambda: self.policy().load(self.receipt, NOW))

    def test_each_sealed_identity_mismatch_denies(self):
        fields = (
            "captain_id", "generation", "anchor_dev", "anchor_ino", "policy_hash",
            "content_hash", "manifest_hash", "source_revision", "effective_at",
            "expires_at", "nonce", "task_id", "run_id", "envelope_hash",
        )
        for field in fields:
            with self.subTest(field=field):
                body = copy.deepcopy(self.body)
                value = body[field]
                if field == "effective_at":
                    body[field] = NOW - 1
                else:
                    body[field] = value + 1 if isinstance(value, int) else f"{value}-drift"
                self.write(body)
                self.assert_frozen(f"{field}-mismatch", lambda: self.policy().load(self.receipt, NOW))

    def test_all_dispatch_paths_reject_snapshot_boundary_drift_including_times(self):
        self.write()
        policy = self.policy()
        snapshot = policy.load(self.receipt, NOW)
        for operation in OPERATIONS:
            for field in ("envelope_hash", "effective_at", "expires_at", "nonce"):
                with self.subTest(operation=operation, field=field):
                    boundary = dict(snapshot.boundary())
                    value = boundary[field]
                    boundary[field] = value + 1 if isinstance(value, int) else f"{value}-drift"
                    self.assert_frozen(
                        "startup-snapshot-drift",
                        lambda op=operation, b=boundary: policy.dispatch(op, b),
                    )
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM mutations").fetchone()[0], 0)

    def test_snapshot_is_immutable_and_cannot_be_reloaded(self):
        self.write()
        policy = self.policy()
        snapshot = policy.load(self.receipt, NOW)
        self.assert_frozen("startup-snapshot-already-loaded", lambda: policy.load(self.receipt, NOW))
        with self.assertRaises((AttributeError, TypeError)):
            getattr(snapshot.boundary(), "__setitem__")("generation", 8)

    def test_disposable_database_is_the_only_mutated_database(self):
        sentinel = self.root / "production-sentinel.sqlite3"
        sentinel.write_bytes(b"production bytes remain opaque")
        before = sentinel.read_bytes()
        self.write()
        policy = self.policy()
        snapshot = policy.load(self.receipt, NOW)
        policy.dispatch("create", snapshot.boundary())
        self.assertEqual(sentinel.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
