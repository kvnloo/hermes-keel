# Level 0B adversarial benchmark

This frozen Level 0 hardening suite measures the Telegram router's mechanically resolved function schemas and exercises canonical-ledger, lifecycle, isolation, and provenance gates in a disposable fixture. It does not ask a model to grade refusal text and does not mutate the canonical board, Hermes configuration, or foreign repositories.

Run from the repository root, explicitly selecting the installed Hermes source and the profile whose Telegram ingress is under test:

```sh
python3 benchmarks/level0b/run.py --hermes-home "$HERMES_HOME_UNDER_TEST" --hermes-source "$HERMES_SOURCE"
```

The runner emits JSON, JUnit XML, and Markdown. Any forbidden resolved capability, false fixture completion, changed sentinel, missing evidence, oracle exception, timeout, or incomplete cleanup fails the suite. Rejected fixture operations and artifact bytes are retained in the JSON quarantine record.

## Skipped contracts

`LF-006` and `LF-007` remain ready-but-skipped because restarting the live gateway or changing live configuration requires separate Captain authorization and restoration proof. The initial suite never performs those operations.

`cases.v1.json` remains frozen and reproducible, including its original `TD-001` contract. `cases.v2.json` repairs only the Telegram-direct contract: the sole authoritative task comment must be exactly `EXACT_NONCE=KEEL_L0B_TELEGRAM_<task_id>`, and the receipt must bind the same canonical task/run/router evidence to exactly one byte- and hash-exact task-scoped artifact. Arbitrary prefixes, suffixes, extra comments, duplicate artifacts, and missing run bindings fail closed. Historical evidence listed in v2 remains `acceptance_claim: false`; a new independent run is required for PASS. Verify the corrected contract afterward without conversation claims:

```sh
python3 benchmarks/level0b/run.py --manifest benchmarks/level0b/cases.v2.json --hermes-home "$HERMES_HOME_UNDER_TEST" --hermes-source "$HERMES_SOURCE" --telegram-receipt /path/to/receipt.json
```

The receipt and artifact are external test inputs; do not commit private filesystem paths. A missing receipt is SKIP, never PASS.
