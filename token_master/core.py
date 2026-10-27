"""Pure evaluation; never mutates Hermes/Kanban state and never calls an LLM."""
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Snapshot:
    provider: str
    observed_at: float
    used_tokens: Optional[int] = None
    limit_tokens: Optional[int] = None
    source: str = "unknown"

@dataclass(frozen=True)
class Estimate:
    task_id: str
    run_id: str
    provider: str
    model: str
    expected_tokens: int
    low_tokens: int
    high_tokens: int
    confidence: float
    duration_seconds: Optional[float] = None
    tool_calls: Optional[int] = None
    trusted: bool = False

@dataclass(frozen=True)
class Anomaly:
    rule: str
    severity: str
    evidence: str
    dedupe_key: str
    attribution: str = "unknown"

@dataclass(frozen=True)
class Thresholds:
    absolute_tokens: int = 100_000
    estimate_multiple: float = 3.0
    burn_rate_tokens_per_minute: float = 20_000
    context_growth_tokens_per_minute: float = 50_000
    cooldown_seconds: float = 900

def evaluate(*, task_id: str, run_id: str, provider: str, observed_tokens: Optional[int], estimate: Optional[Estimate], elapsed_seconds: Optional[float], previous: Optional[Snapshot] = None, current: Optional[Snapshot] = None, thresholds: Thresholds = Thresholds(), alerted: Optional[set[str]] = None) -> list[Anomaly]:
    """Return advisory anomalies. Missing counters and mismatched attribution fail closed."""
    out=[]; alerted=alerted or set()
    def add(rule, severity, evidence):
        key=f"{task_id}:{run_id}:{rule}"
        if key not in alerted: out.append(Anomaly(rule,severity,evidence,key,"task-run" if run_id else "unknown"))
    if observed_tokens is None: return out
    if observed_tokens < 0: add("invalid-counter","warning","negative counter")
    if observed_tokens >= thresholds.absolute_tokens: add("absolute-threshold","warning",f"tokens={observed_tokens}")
    if estimate and estimate.provider != provider: add("provider-mismatch","warning","estimate provider differs from telemetry")
    if estimate and estimate.expected_tokens > 0 and observed_tokens >= estimate.expected_tokens * thresholds.estimate_multiple: add("estimate-multiple","warning",f"observed={observed_tokens}; expected={estimate.expected_tokens}")
    if elapsed_seconds and elapsed_seconds > 0 and observed_tokens/elapsed_seconds*60 >= thresholds.burn_rate_tokens_per_minute: add("burn-rate","warning",f"tokens_per_minute={observed_tokens/elapsed_seconds*60:.0f}")
    if previous and current and current.used_tokens is not None and previous.used_tokens is not None and current.observed_at > previous.observed_at:
        delta=current.used_tokens-previous.used_tokens
        mins=(current.observed_at-previous.observed_at)/60
        if delta >= 0 and mins and delta/mins >= thresholds.context_growth_tokens_per_minute: add("context-growth","warning",f"delta={delta}; minutes={mins:.2f}")
        if delta < 0: add("counter-reset","info","counter decreased; delta treated as unknown")
    return out
