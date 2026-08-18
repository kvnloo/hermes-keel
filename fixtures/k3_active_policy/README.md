# K3 disposable ACTIVE-policy fixture

This pack is a synthetic, local-only oracle. It does not configure a key provider,
wire the Hermes dispatcher, activate focused mode, touch a production board, or
claim Level 1. Tests create all receipts, anchors, and SQLite databases under a
temporary directory.

The receipt binds explicit Captain identity, generation, anchor device/inode,
policy/content/manifest hashes, effective/expiry times, nonce,
task/run/envelope identity, and source revision. Startup consumes the nonce once
and freezes one immutable
snapshot. Synthetic create/promote/claim/spawn mutations all cross the same full
snapshot comparison. Any missing, expired, replayed, mismatched, malformed, or
unverifiable ACTIVE receipt remains FROZEN.

Run: `python -m unittest fixtures.k3_active_policy.test_fixture -v`
