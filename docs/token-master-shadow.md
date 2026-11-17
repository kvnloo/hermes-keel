# Token Master shadow-mode prototype (v0.1)

## Contract

`token_master` is an isolated, read-only advisory layer. `CodexBarCollector` invokes the supported `codexbar usage --format json` interface and retains only provider, timestamp, numeric counters, and source. It does not read credentials/config files, retain account labels, prompts, URLs, or raw output. CodexBar dashboard counters are subscription-level and cannot be mechanically attributed to a Hermes task/run; attribution is `unknown` unless a future Keel receipt joins exact canonical `task_id` + `run_id` + provider/model.

`Estimate` is an untrusted plan receipt: expected interval, confidence, duration, tool-call count, provider/model, and explicit trust=false. A future append-only receipt writer must use idempotency `(type, task_id, run_id, source_hash, revision)` and never compete with Kanban.

## Deterministic gates

Before Luna: missing/invalid counter, absolute 100,000 tokens, observed >= 3x estimate, 20,000 tokens/minute burn, 50,000 tokens/minute context growth, provider mismatch, and counter reset. Thresholds are configurable. Alerts dedupe by task/run/rule and callers add cooldown/hysteresis. This prototype emits no Telegram/Kanban mutation. Luna is permitted only at bounded plan-review, anomaly-escalation, or post-run calibration events; cap and account its own spend. Advice cannot change routing, prompts, stop/cancel work, or deny execution.

## Current truth and gaps

CodexBar 0.42.1 documents `usage` JSON, provider selection, all-account mode, and provider-specific web/CLI fallback. A live all-provider read completed, but some providers reported unavailable CLIs; this is a collector warning, not a token estimate. No stable CodexBar task attribution or local export was found. Hermes Keel currently has no usage fields or accounting, and the inspected repository has only canonical evidence/Level-0 tests. Therefore exact cost, task attribution, subscription headroom, retries, and shared-account allocation remain unknown. Never infer cost from subscription counters.

Available token-saving mechanisms were not enabled or installed by this prototype. Repository search found no GitNexus, sol-advisor, or accounting plugin in Keel; recommendations must be conditional on worker capability and marginal value. Existing compact search/read tools should be preferred over large dumps.

## Failure behavior / privacy

Collector failure, malformed/partial JSON, clock skew, resets, duplicate receipts, gateway restart, and Luna failure are non-fatal and produce no execution mutation. Keep redacted receipts only as long as required for calibration; hash canonical metadata, not secrets. Never log command output or credentials. Service installation and scheduling are intentionally disabled.

## Verification

`python -m pytest -q` (existing suite) and `python -m unittest token_master.test_core` pass. Tests cover missing counters, runaway/estimate multiple, provider mismatch, reset, concurrent run dedupe, and no mutation. The pure evaluator has no network, filesystem, or Hermes imports.

## Decision for Kevin

Enable shadow collection only as a manually invoked, read-only job first (not a background scheduler). Start with the conservative defaults above, alert-only, and review one week of precision/false positives before any scheduling or Level-1 proposal. Subscription headroom should remain an explicitly unknown advisory field until a mechanically attributed provider receipt exists.
