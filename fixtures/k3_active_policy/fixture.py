"""Disposable K3 ACTIVE-policy fixture; never a production policy loader."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

SCHEMA = "keel.synthetic-active-policy.v1"
OPERATIONS = ("create", "promote", "claim", "spawn")


class Frozen(RuntimeError):
    """Fail-closed policy or immutable-snapshot boundary rejection."""


def canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sign(body: Mapping[str, object], key: bytes) -> dict[str, object]:
    return {**body, "mac": hmac.new(key, canonical(body), hashlib.sha256).hexdigest()}


@dataclass(frozen=True)
class StartupSnapshot:
    generation: int
    captain_id: str
    anchor_dev: int
    anchor_ino: int
    policy_hash: str
    content_hash: str
    manifest_hash: str
    source_revision: str
    nonce: str
    effective_at: int
    expires_at: int
    task_id: str
    run_id: int
    envelope_hash: str

    def boundary(self) -> Mapping[str, object]:
        return MappingProxyType({
            "generation": self.generation,
            "captain_id": self.captain_id,
            "anchor_dev": self.anchor_dev,
            "anchor_ino": self.anchor_ino,
            "policy_hash": self.policy_hash,
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "source_revision": self.source_revision,
            "nonce": self.nonce,
            "effective_at": self.effective_at,
            "expires_at": self.expires_at,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "envelope_hash": self.envelope_hash,
        })


class DisposablePolicy:
    """Loads one ACTIVE receipt and gates synthetic dispatcher mutations."""

    REQUIRED = frozenset({
        "schema", "status", "captain_id", "generation", "anchor_dev", "anchor_ino",
        "policy_hash", "content_hash", "manifest_hash", "source_revision", "effective_at",
        "expires_at", "nonce", "task_id", "run_id", "envelope_hash", "mac",
    })

    def __init__(self, db: Path, key_provider: Callable[[], bytes | None], expected: Mapping[str, object]):
        self.db = db
        self.key_provider = key_provider
        self.expected = dict(expected)
        self.snapshot: StartupSnapshot | None = None
        with sqlite3.connect(db) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS spent_nonces (nonce TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS mutations (
                    seq INTEGER PRIMARY KEY, operation TEXT NOT NULL, task_id TEXT NOT NULL,
                    run_id INTEGER NOT NULL, envelope_hash TEXT NOT NULL, generation INTEGER NOT NULL
                );
            """)

    def load(self, receipt_path: Path, now: int | None = None) -> StartupSnapshot:
        if self.snapshot is not None:
            raise Frozen("startup-snapshot-already-loaded")
        key = self.key_provider()
        if not key:
            raise Frozen("key-provider-unavailable")
        try:
            raw = receipt_path.read_bytes()
            receipt = json.loads(raw)
        except (OSError, ValueError, TypeError) as exc:
            raise Frozen("missing-or-malformed-active") from exc
        if not isinstance(receipt, dict) or set(receipt) != self.REQUIRED:
            raise Frozen("receipt-schema-mismatch")
        mac = receipt.pop("mac")
        if not isinstance(mac, str) or not hmac.compare_digest(mac, hmac.new(key, canonical(receipt), hashlib.sha256).hexdigest()):
            raise Frozen("receipt-mac-mismatch")
        if receipt["schema"] != SCHEMA or receipt["status"] != "ACTIVE":
            raise Frozen("active-required")
        current = int(time.time()) if now is None else now
        if not isinstance(receipt["effective_at"], int) or receipt["effective_at"] > current:
            raise Frozen("active-not-yet-effective")
        if not isinstance(receipt["expires_at"], int) or receipt["expires_at"] <= current:
            raise Frozen("active-expired")
        for field, value in self.expected.items():
            if receipt.get(field) != value:
                raise Frozen(f"{field}-mismatch")
        try:
            snapshot = StartupSnapshot(**{key: receipt[key] for key in StartupSnapshot.__dataclass_fields__})
        except (KeyError, TypeError) as exc:
            raise Frozen("receipt-type-mismatch") from exc
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute("INSERT INTO spent_nonces(nonce) VALUES (?)", (snapshot.nonce,))
        except sqlite3.IntegrityError as exc:
            raise Frozen("active-replayed") from exc
        self.snapshot = snapshot
        return snapshot

    def dispatch(self, operation: str, boundary: Mapping[str, object]) -> None:
        if self.snapshot is None:
            raise Frozen("active-snapshot-missing")
        if operation not in OPERATIONS:
            raise Frozen("unknown-dispatch-operation")
        # Every lifecycle mutation compares the complete, immutable startup tuple.
        if dict(boundary) != dict(self.snapshot.boundary()):
            raise Frozen("startup-snapshot-drift")
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO mutations(operation,task_id,run_id,envelope_hash,generation) VALUES (?,?,?,?,?)",
                (operation, self.snapshot.task_id, self.snapshot.run_id,
                 self.snapshot.envelope_hash, self.snapshot.generation),
            )


def synthetic_body(anchor: Path, now: int = 1_800_000_000) -> dict[str, object]:
    stat = anchor.stat()
    return {
        "schema": SCHEMA,
        "status": "ACTIVE",
        "captain_id": "captain:test-only",
        "generation": 7,
        "anchor_dev": stat.st_dev,
        "anchor_ino": stat.st_ino,
        "policy_hash": "1" * 64,
        "content_hash": "2" * 64,
        "manifest_hash": "3" * 64,
        "source_revision": "fixture-revision-1",
        "effective_at": now,
        "expires_at": now + 60,
        "nonce": "fixture-nonce-0001",
        "task_id": "t_fixture",
        "run_id": 42,
        "envelope_hash": "4" * 64,
    }
