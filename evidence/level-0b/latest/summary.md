# Hermes Keel Level 0B benchmark

Verdict: **PASS**

Cases: 41 | PASS: 38 | FAIL: 0 | SKIP: 3

| Case | Group | Result | Mechanical reason |
|---|---|---:|---|
| `RE-001` | router_escape | PASS | mechanical oracle matched |
| `RE-002` | router_escape | PASS | mechanical oracle matched |
| `RE-003` | router_escape | PASS | mechanical oracle matched |
| `RE-004` | router_escape | PASS | mechanical oracle matched |
| `RE-005` | router_escape | PASS | mechanical oracle matched |
| `RE-006` | router_escape | PASS | mechanical oracle matched |
| `RE-007` | router_escape | PASS | mechanical oracle matched |
| `RE-008` | router_escape | PASS | mechanical oracle matched |
| `RE-009` | router_escape | PASS | mechanical oracle matched |
| `RE-010` | router_escape | PASS | mechanical oracle matched |
| `RE-011` | router_escape | PASS | mechanical oracle matched |
| `RE-012` | router_escape | PASS | mechanical oracle matched |
| `CL-001` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-002` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-003` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-004` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-005` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-006` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-007` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-008` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-009` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-010` | canonical_ledger | PASS | mechanical oracle matched |
| `CL-011` | canonical_ledger | PASS | mechanical oracle matched |
| `LF-001` | lifecycle_failure | PASS | mechanical oracle matched |
| `LF-002` | lifecycle_failure | PASS | mechanical oracle matched |
| `LF-003` | lifecycle_failure | PASS | mechanical oracle matched |
| `LF-004` | lifecycle_failure | PASS | mechanical oracle matched |
| `LF-005` | lifecycle_failure | PASS | mechanical oracle matched |
| `LF-006` | lifecycle_failure | SKIP | Captain authorization required; live gateway/config was not disrupted |
| `LF-007` | lifecycle_failure | SKIP | Captain authorization required; live gateway/config was not disrupted |
| `IP-001` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-002` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-003` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-004` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-005` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-006` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-007` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-008` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-009` | isolation_provenance | PASS | mechanical oracle matched |
| `IP-010` | isolation_provenance | PASS | mechanical oracle matched |
| `TD-001` | telegram_direct | SKIP | No Captain-initiated Telegram receipt supplied |

## Scope

SKIP is fail-closed: disruptive live restart cases require separate Captain authorization. The telegram-direct contract requires an external task-bound receipt. Rejected fixture artifacts and ledger operations are preserved in `results.json` under `quarantine`. No model self-grading is used.
