"""
Run records and statistics.

``RunResult`` is the flat record of one benchmark run — everything the CSV,
JSON, plots and LaTeX tables are built from.  ``summarize()`` turns a list
of numbers into the descriptive statistics reported in the paper
(min / max / mean / median / standard deviation / 95th percentile).
"""

import statistics
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RunResult:
    """Everything recorded about a single benchmark run."""

    # ---- identification -----------------------------------------------------
    architecture: str          # "single_agent" or "multi_agent"
    model: str                 # e.g. "ollama_chat/qwen3:8b"
    scenario: str              # e.g. "bandit_static_code"
    concurrency: int           # concurrency level this run executed under
    run_idx: int               # 0-based index within the measured runs
    warmup: bool               # True for warm-up runs (excluded from stats)
    intent_variant: int = 0    # frozen intent variant sent (run_idx % #variants)

    # ---- outcome ------------------------------------------------------------
    status: str = "OK"         # "OK" or "FAILED"
    error: Optional[str] = None

    # ---- latency metrics (milliseconds) --------------------------------------
    # End-to-end: request submitted -> final response consumed.
    e2e_ms: float = 0.0
    # Time until the orchestrator made its routing decision (first tool call
    # in Arch B / transfer_to_agent in Arch A).
    selection_ms: Optional[float] = None
    # Total LLM + framework time (= e2e - tool execution time).
    llm_ms: Optional[float] = None
    # Authoritative tool execution time from the timing wrapper.
    tool_ms: Optional[float] = None
    # Response formatting: final-response timestamp - last tool-response
    # timestamp (the LLM summarising the tool result).
    format_ms: Optional[float] = None

    # ---- resource metrics (whole benchmark process) --------------------------
    cpu_avg: float = 0.0
    cpu_peak: float = 0.0
    rss_avg_mb: float = 0.0
    rss_peak_mb: float = 0.0

    # ---- token metrics (None -> reported as "N/A") ----------------------------
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # ---- routing -------------------------------------------------------------
    selected: Optional[str] = None   # tool fn (Arch B) / specialist agent (Arch A)
    expected: Optional[str] = None
    routing_correct: bool = False

    # ---- raw event timeline (kept in the JSON for deep analysis) --------------
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    final_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-dict form for JSON serialisation."""
        return asdict(self)


def summarize(values: List[float]) -> Dict[str, float]:
    """
    Descriptive statistics for one metric across the measured runs.

    Returns min, max, mean, median, stdev, and the 95th percentile — the
    standard set for latency reporting in systems papers (p95 captures tail
    behaviour that the mean hides).
    """
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0,
                "stdev": 0.0, "p95": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        # stdev needs at least two data points.
        "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
        # quantiles(n=20) returns 19 cut points; index 18 is the 95th percentile.
        "p95": statistics.quantiles(values, n=20)[18] if len(values) >= 2 else values[0],
    }
