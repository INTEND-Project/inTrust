"""
Instrumentation for the benchmark: tool-execution timing and OS resource
sampling.

Two independent mechanisms live here:

1. ``RunCollector`` + ``make_timed_skill`` — wraps each skill's execute
   function with high-resolution timers.  This gives the AUTHORITATIVE tool
   execution time (the ADK event stream also allows deriving it from event
   timestamps, but the wrapper measures exactly the subprocess work without
   any event-delivery latency).

2. ``ResourceSampler`` — a small background thread that samples, every
   100 ms via psutil, THREE resource layers (the paper compares the
   RESOURCE COST of the two architectures, not only their latency):

   - the benchmark HARNESS process (cpu_*, rss_*): orchestration overhead
     of the ADK client — small, and mostly idle-on-HTTP during generation;
   - the OLLAMA SERVER process tree (server_cpu_*, server_rss_*): where
     inference actually happens — the meaningful CPU/RAM cost.  RSS summed
     over the serve process and its model-runner children double-counts
     shared pages; treat absolute values as an upper bound and deltas
     between cells as the signal.  Requires the server to run on the SAME
     host (as in the Slurm campaign jobs); otherwise the fields are None;
   - the GPU via ``nvidia-smi`` (gpu_util_*, vram_*), sampled every 500 ms:
     the headline resource on GPU machines.  None when nvidia-smi is
     unavailable.
"""

import dataclasses
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

import psutil

from orchestrator.skill_loader import AssessmentSkill


class SilentLogger:
    """
    No-op logger passed to skills during benchmark runs.

    The production ``NullLogger`` prints to stdout, which would add several
    lines per run to the campaign output.  Skill/tool outcomes are already
    captured by the timing wrapper and the run results, so nothing is lost.
    """

    def info(self, component: str, message: str) -> None:
        pass

    def warning(self, component: str, message: str) -> None:
        pass

    def error(self, component: str, message: str) -> None:
        pass

    def exception(self, component: str, message: str, exc: BaseException) -> None:
        pass


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
    Background thread sampling harness, Ollama-server, and GPU resources.

    Usage::

        sampler = ResourceSampler()
        sampler.start()
        ... run the benchmark work ...
        stats = sampler.stop()   # {"cpu_avg": ..., "server_rss_peak_mb": ...,
                                 #  "gpu_util_avg": ..., ...}

    Server/GPU keys are ``None`` when there is nothing to sample (no local
    Ollama process, no nvidia-smi).  Note: in concurrent (throughput) mode
    the sampler measures the shared server/GPU load of the whole wave, and
    the harness numbers aggregate all in-flight runs.
    """

    SAMPLE_INTERVAL_SEC = 0.1
    # Rescan for Ollama processes every N ticks (model-runner children are
    # spawned when a model loads) and query nvidia-smi every M ticks
    # (spawning it is too expensive for the 100 ms cadence).
    SERVER_RESCAN_TICKS = 10
    GPU_SAMPLE_TICKS = 5

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cpu_samples: List[float] = []
        self._rss_samples: List[int] = []
        self._server_cpu_samples: List[float] = []
        self._server_rss_samples: List[int] = []
        self._gpu_util_samples: List[float] = []
        self._vram_samples: List[float] = []
        self._server_procs: List[psutil.Process] = []
        self._nvidia_smi = shutil.which("nvidia-smi")

    def _rescan_server_procs(self) -> None:
        """Find the Ollama serve process and its model-runner children.

        The model runner that actually holds the weights is a CHILD process
        of ``ollama serve`` and is not necessarily named "ollama" (current
        Ollama spawns ``llama-server``), so both the name match and the
        recursive children of every match are tracked.
        """
        own_pid = self._process.pid
        procs: List[psutil.Process] = []
        try:
            for proc in psutil.process_iter(["name"]):
                name = (proc.info.get("name") or "").lower()
                if ("ollama" in name or "llama-server" in name) and proc.pid != own_pid:
                    procs.append(proc)
                    try:
                        procs.extend(proc.children(recursive=True))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            # De-duplicate (children may also match by name).
            procs = list({p.pid: p for p in procs}.values())
        except (psutil.Error, OSError):
            return  # keep the previous process list on scan failure
        # Keep already-tracked Process objects (their cpu_percent baselines
        # stay valid); add newly discovered ones.
        known = {p.pid for p in self._server_procs}
        for proc in procs:
            if proc.pid not in known:
                try:
                    proc.cpu_percent(interval=None)  # establish baseline
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                self._server_procs.append(proc)
        alive = {p.pid for p in procs}
        self._server_procs = [p for p in self._server_procs if p.pid in alive]

    def _sample_server(self) -> None:
        cpu_total, rss_total, seen = 0.0, 0, False
        for proc in self._server_procs:
            try:
                cpu_total += proc.cpu_percent(interval=None)
                rss_total += proc.memory_info().rss
                seen = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if seen:
            self._server_cpu_samples.append(cpu_total)
            self._server_rss_samples.append(rss_total)

    def _sample_gpu(self) -> None:
        try:
            out = subprocess.run(
                [self._nvidia_smi, "--query-gpu=utilization.gpu,memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
            )
            if out.returncode != 0:
                return
            # One line per GPU; sum VRAM, take max utilisation across GPUs.
            utils, vrams = [], []
            for line in out.stdout.strip().splitlines():
                util_s, vram_s = line.split(",")
                utils.append(float(util_s))
                vrams.append(float(vram_s))
            if utils:
                self._gpu_util_samples.append(max(utils))
                self._vram_samples.append(sum(vrams))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass  # GPU sampling is best-effort

    def start(self) -> None:
        """Start sampling in a daemon thread."""
        # First cpu_percent() call establishes the measurement baseline and
        # returns a meaningless 0.0 — call it once before sampling begins.
        self._process.cpu_percent(interval=None)
        self._rescan_server_procs()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def _sample_loop(self) -> None:
        tick = 0
        while not self._stop_event.wait(self.SAMPLE_INTERVAL_SEC):
            tick += 1
            self._cpu_samples.append(self._process.cpu_percent(interval=None))
            self._rss_samples.append(self._process.memory_info().rss)
            if tick % self.SERVER_RESCAN_TICKS == 0:
                self._rescan_server_procs()
            self._sample_server()
            if self._nvidia_smi and tick % self.GPU_SAMPLE_TICKS == 0:
                self._sample_gpu()

    @staticmethod
    def _avg_peak(samples: List[float], scale: float = 1.0):
        """(avg, peak) of a sample list, or (None, None) when empty."""
        if not samples:
            return None, None
        return (sum(samples) / len(samples) * scale, max(samples) * scale)

    def stop(self) -> Dict[str, Optional[float]]:
        """Stop sampling and return aggregate resource statistics."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

        if not self._cpu_samples:
            # Run finished faster than one sample interval; take one sample
            # now so we never return empty harness statistics.
            self._cpu_samples.append(self._process.cpu_percent(interval=None))
            self._rss_samples.append(self._process.memory_info().rss)
            self._sample_server()

        to_mb = 1.0 / (1024 * 1024)
        cpu_avg, cpu_peak = self._avg_peak(self._cpu_samples)
        rss_avg, rss_peak = self._avg_peak(self._rss_samples, to_mb)
        srv_cpu_avg, srv_cpu_peak = self._avg_peak(self._server_cpu_samples)
        srv_rss_avg, srv_rss_peak = self._avg_peak(self._server_rss_samples, to_mb)
        gpu_avg, gpu_peak = self._avg_peak(self._gpu_util_samples)
        vram_avg, vram_peak = self._avg_peak(self._vram_samples)
        return {
            "cpu_avg": cpu_avg,
            "cpu_peak": cpu_peak,
            "rss_avg_mb": rss_avg,
            "rss_peak_mb": rss_peak,
            "server_cpu_avg": srv_cpu_avg,
            "server_cpu_peak": srv_cpu_peak,
            "server_rss_avg_mb": srv_rss_avg,
            "server_rss_peak_mb": srv_rss_peak,
            "gpu_util_avg": gpu_avg,
            "gpu_util_peak": gpu_peak,
            "vram_avg_mb": vram_avg,
            "vram_peak_mb": vram_peak,
        }
