"""
Asynchronous job execution engine.

This module contains the ``execute_job()`` coroutine, which is the heart of
InTrust's runtime.  When a new intent is submitted via the HTTP API, a job
record is created in the database and ``execute_job()`` is launched as a
background asyncio task.  The HTTP response is returned immediately; the
client polls ``/result/{job_id}`` until the job completes.

High-level execution flow
-------------------------
1. Load the job and its associated intent from the database.
2. Update the job status to RUNNING.
3. Load all available skills and create an orchestrator instance.
4. The orchestrator calls the LLM to select the best skill for the intent.
5. Run the selected skill (inside a thread to avoid blocking the event loop).
6. Store the result and update the job status to COMPLETED or FAILED.
7. Save execution metadata (timing, environment, tool versions).
"""

import asyncio
import contextlib
import io
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

from api.database import (
    ExecutionMetadataRecord,
    IntentRecord,
    JobRecord,
    ResultRecord,
    SessionLocal,
)
from api.models import JobStatus
from orchestrator.agent import RuntimeOrchestrator
from orchestrator.skill_loader import load_skills
from services.logging_service import JobLogger


def _now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _run_version(command: list[str]) -> str | None:
    """
    Run a CLI command and return its first line of output.

    Used to detect installed tool versions (bandit, trivy) for the execution
    metadata record.  Returns ``None`` if the command is not found or fails.
    """
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    output = (process.stdout or process.stderr or "").strip()
    return output.splitlines()[0] if output else None


def _tool_versions() -> Dict[str, Any]:
    """
    Detect and return the versions of the external assessment tools.

    These are stored in the execution metadata record alongside each job so
    that results are reproducible and tool upgrades are traceable.
    """
    return {
        "bandit": _run_version(["bandit", "--version"]),
        "trivy": _run_version(["trivy", "--version"]),
    }


def _execute_with_captured_output(
    orchestrator: RuntimeOrchestrator,
    intent: Any,
    logger: JobLogger,
) -> Dict[str, Any]:
    """
    Run the orchestrator and capture any stray stdout/stderr output.

    External tools (bandit, trivy) occasionally write directly to stdout or
    stderr rather than going through the logger.  This wrapper captures that
    output and routes it through the JobLogger so it appears in the job's
    execution log.
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        report = orchestrator.execute(intent, logger)

    captured_stdout = stdout_buf.getvalue().strip()
    captured_stderr = stderr_buf.getvalue().strip()
    if captured_stdout:
        logger.info("subprocess.stdout", captured_stdout)
    if captured_stderr:
        logger.warning("subprocess.stderr", captured_stderr)
    return report


def _summary_from_report(report: Dict[str, Any]) -> str | None:
    """Extract a human-readable summary from the assessment report."""
    return (
        report.get("explanation")
        or report.get("result", {}).get("explanation")
        or report.get("summary")
    )


def _recommendation_from_report(report: Dict[str, Any]) -> str | None:
    """Extract actionable recommendations from the assessment report."""
    return (
        report.get("recommendations")
        or report.get("result", {}).get("recommendations")
        or report.get("recommendation")
    )


async def execute_job(job_id: str) -> None:
    """
    Run a queued assessment job end-to-end.

    This coroutine is launched as a background task by the ``/intent``
    endpoint.  It manages the full job lifecycle: status updates, skill
    execution, result storage, and error handling.

    Parameters
    ----------
    job_id : str
        The job identifier created when the intent was submitted.
    """
    db = SessionLocal()
    logger = JobLogger(job_id)
    started = time.perf_counter()
    report: Dict[str, Any] | None = None

    try:
        # --- Step 1: Load the job and intent from the database ---
        job = db.get(JobRecord, job_id)
        if not job:
            # Should not happen in normal operation; guard against stale calls.
            return

        intent_record = db.get(IntentRecord, job.intent_id)
        if not intent_record:
            raise RuntimeError(f"Intent record not found for job {job_id}")

        intent = intent_record.raw_intent_json

        # --- Step 2: Mark the job as running ---
        job.status = JobStatus.RUNNING.value
        job.started_at = _now()
        job.updated_at = _now()
        db.commit()

        logger.info(
            "intent",
            "[Intent Received]\n"
            f"intent_id={job.intent_id}\n"
            f"assessment_type={job.assessment_type}\n"
            f"timestamp={_now().isoformat()}",
        )
        logger.info("executor", f"Job started: job_id={job_id}")

        # --- Step 3: Load skills and create the orchestrator ---
        # Skills are loaded fresh for each job so that any changes to the
        # skills/ directory take effect without restarting the service.
        registry = load_skills()
        logger.info(
            "skill_loader",
            "Loaded assessment skills: "
            + ", ".join(skill.name for skill in registry.list()),
        )
        orchestrator = RuntimeOrchestrator(registry)

        # --- Step 4 & 5: Let the orchestrator select and execute the skill ---
        # We run the synchronous orchestrator.execute() inside a thread pool
        # worker (asyncio.to_thread) so it does not block the event loop
        # while the skill runs its external tool (bandit, trivy, etc.).
        report = await asyncio.to_thread(
            _execute_with_captured_output, orchestrator, intent, logger
        )

        # --- Step 6: Store the result and update the job status ---
        lifecycle_status = report.get("lifecycleStatus")
        job.status = (
            JobStatus.COMPLETED.value
            if lifecycle_status == "completed"
            else JobStatus.FAILED.value
        )
        job.completed_at = _now()
        job.updated_at = _now()

        db.merge(
            ResultRecord(
                job_id=job_id,
                result_json=report,
                summary=_summary_from_report(report),
                recommendation=_recommendation_from_report(report),
            )
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "executor",
            "[Assessment Completed]\n"
            f"job_id={job_id}\n"
            f"duration_ms={duration_ms}\n"
            f"status={job.status}",
        )

    except Exception as exc:
        # Log the full error and mark the job as failed.  We do not re-raise
        # because this coroutine runs as a fire-and-forget background task —
        # there is no caller to catch the exception.
        logger.exception("executor", f"Job failed: {exc}", exc)
        job = db.get(JobRecord, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.completed_at = _now()
            job.updated_at = _now()
        # Store a minimal failure report so the /result endpoint has something
        # to return even when the skill never ran.
        report = {
            "intentId": job.intent_id if job else None,
            "lifecycleStatus": "failed",
            "error": str(exc),
        }
        db.merge(
            ResultRecord(
                job_id=job_id,
                result_json=report,
                summary="Assessment execution failed",
                recommendation="Inspect execution logs and retry after resolving the error.",
            )
        )

    finally:
        # --- Step 7: Save execution metadata ---
        # This block always runs, even if an exception occurred above.
        execution_time_ms = int((time.perf_counter() - started) * 1000)
        job = db.get(JobRecord, job_id)
        input_parameters = None
        if job:
            intent_record = db.get(IntentRecord, job.intent_id)
            if intent_record:
                input_parameters = intent_record.raw_intent_json.get("parameters", {})

        # Retrieve the skill name that was recorded in the report, if any.
        skill_name = report.get("skill") if report else None

        db.merge(
            ExecutionMetadataRecord(
                job_id=job_id,
                agent_name=AGENT_NAME,
                skill_name=skill_name,
                execution_time_ms=execution_time_ms,
                host_name=socket.gethostname(),
                python_version=sys.version,
                os_info=f"{platform.system()} {platform.release()}",
                tool_versions=_tool_versions(),
                input_parameters=input_parameters,
                output_summary={
                    "status": report.get("lifecycleStatus") if report else None,
                    "assessmentType": report.get("assessmentType") if report else None,
                    "summary": _summary_from_report(report or {}),
                },
            )
        )
        db.commit()
        db.close()


# The agent name constant is imported from the orchestrator module in the
# original code.  We define it here to avoid an extra import in the finally
# block where we just need the string.
AGENT_NAME = "InTrustRuntimeOrchestrator"
