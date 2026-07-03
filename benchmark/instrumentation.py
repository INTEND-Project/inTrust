"""
Instrumentation for the benchmark: tool-execution timing and OS resource
sampling.

Two independent mechanisms live here:

1. ``RunCollector`` + ``make_timed_skill`` — wraps each skill's execute
   function with high-resolution timers.  This gives the AUTHORITATIVE tool
   execution time (the ADK event stream also allows deriving it from event
   timestamps, but the wrapper measures exactly the subprocess work without
   any event-delivery latency).

2. ``ResourceSampler`` — a small background thread that samples the current
   process's CPU utilisation and RSS memory every 100 ms via psutil.  CPU and
   memory are collected because the paper compares the RESOURCE COST of the
   two architectures, not only their latency: the multi-agent architecture
   performs more LLM round-trips, which may show up as higher CPU time in
   the benchmark process and higher memory pressure on the Ollama server.
"""

import dataclasses
import threading
import time
from typing import Any, Dict, List, Optional

import psutil

from orchestrator.skill_loader import AssessmentSkill


class RunCollector:
    """
    Mutable per-run record filled in by the timed tool wrappers.

    One collector is created per benchmark run and threaded (via closure)
    into the tools of the agent built for that run.  After the run finishes
    the runner reads the recorded tool timings out of it.
    """

    def __init__(self) -> None:
        # Each entry: {"skill": name, "started": float, "finished": float,
        #              "duration_sec": float, "status": str}
        self.tool_calls: List[Dict[str, Any]] = []

    @property
    def total_tool_time_sec(self) -> float:
        """Sum of all tool execution durations in this run (usually one)."""
        return sum(entry["duration_sec"] for entry in self.tool_calls)


def make_timed_skill(skill: AssessmentSkill, collector: RunCollector) -> AssessmentSkill:
    """
    Return a copy of ``skill`` whose execute function records its own timing.

    Uses ``time.perf_counter()`` (monotonic, high resolution) for the
    duration and ``time.time()`` (wall clock) for the start/finish stamps so
    they can be aligned with the ADK event timestamps, which are wall clock.
    """
    real_execute = skill.execute

    def timed_execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
        wall_started = time.time()
        perf_started = time.perf_counter()
        error = None
        try:
            result = real_execute(intent, logger)
            if isinstance(result, dict):
                status = result.get("status", "UNKNOWN")
                error = result.get("error")
            else:
                status = "UNKNOWN"
            return result
        except Exception as exc:
            status = "EXCEPTION"
            error = str(exc)
            raise
        finally:
            duration = time.perf_counter() - perf_started
            collector.tool_calls.append(
                {
                    "skill": skill.name,
                    "started": wall_started,
                    "finished": wall_started + duration,
                    "duration_sec": duration,
                    "status": status,
                    "error": error,
                }
            )

    # dataclasses.replace() keeps every other field (name, docs, ...) intact.
    return dataclasses.replace(skill, execute=timed_execute)


class ResourceSampler:
    """
    Background thread sampling CPU %% and RSS memory of this process.

    Usage::

        sampler = ResourceSampler()
        sampler.start()
        ... run the benchmark work ...
        stats = sampler.stop()   # {"cpu_avg": ..., "cpu_peak": ...,
                                 #  "rss_avg_mb": ..., "rss_peak_mb": ...}

    Note: in concurrent (throughput) mode the sampler still measures the
    whole benchmark process, i.e. the aggregate of all in-flight runs.
    """

    SAMPLE_INTERVAL_SEC = 0.1

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cpu_samples: List[float] = []
        self._rss_samples: List[int] = []

    def start(self) -> None:
        """Start sampling in a daemon thread."""
        # First cpu_percent() call establishes the measurement baseline and
        # returns a meaningless 0.0 — call it once before sampling begins.
        self._process.cpu_percent(interval=None)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def _sample_loop(self) -> None:
        while not self._stop_event.wait(self.SAMPLE_INTERVAL_SEC):
            self._cpu_samples.append(self._process.cpu_percent(interval=None))
            self._rss_samples.append(self._process.memory_info().rss)

    def stop(self) -> Dict[str, float]:
        """Stop sampling and return aggregate CPU / memory statistics."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

        if not self._cpu_samples:
            # Run finished faster than one sample interval; take one sample
            # now so we never return empty statistics.
            self._cpu_samples.append(self._process.cpu_percent(interval=None))
            self._rss_samples.append(self._process.memory_info().rss)

        to_mb = 1.0 / (1024 * 1024)
        return {
            "cpu_avg": sum(self._cpu_samples) / len(self._cpu_samples),
            "cpu_peak": max(self._cpu_samples),
            "rss_avg_mb": sum(self._rss_samples) / len(self._rss_samples) * to_mb,
            "rss_peak_mb": max(self._rss_samples) * to_mb,
        }
