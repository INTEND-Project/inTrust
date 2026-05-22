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
    return datetime.now(timezone.utc)


def _run_version(command: list[str]) -> str | None:
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
    return {
        "bandit": _run_version(["bandit", "--version"]),
        "trivy": _run_version(["trivy", "--version"]),
    }


def _execute_with_captured_output(orchestrator, intent, logger) -> Dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        report = orchestrator.execute(intent, logger)

    stdout_value = stdout.getvalue().strip()
    stderr_value = stderr.getvalue().strip()
    if stdout_value:
        logger.info("subprocess.stdout", stdout_value)
    if stderr_value:
        logger.warning("subprocess.stderr", stderr_value)
    return report


def _summary_from_report(report: Dict[str, Any]) -> str | None:
    return (
        report.get("explanation")
        or report.get("result", {}).get("explanation")
        or report.get("summary")
    )


def _recommendation_from_report(report: Dict[str, Any]) -> str | None:
    return (
        report.get("recommendations")
        or report.get("result", {}).get("recommendations")
        or report.get("recommendation")
    )


async def execute_job(job_id: str) -> None:
    db = SessionLocal()
    logger = JobLogger(job_id)
    started = time.perf_counter()
    selected_skill = None
    report: Dict[str, Any] | None = None

    try:
        job = db.get(JobRecord, job_id)
        if not job:
            return

        intent_record = db.get(IntentRecord, job.intent_id)
        if not intent_record:
            raise RuntimeError(f"Intent record not found for job {job_id}")

        intent = intent_record.raw_intent_json
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
        registry = load_skills()
        logger.info(
            "skill_loader",
            "Loaded assessment skills: "
            + ", ".join(skill.name for skill in registry.list()),
        )
        orchestrator = RuntimeOrchestrator(registry)
        selected_skill = orchestrator.select_skill(intent)
        logger.info(
            "orchestrator",
            "[Orchestrator]\n"
            f"Selected skill: {selected_skill.name}\n"
            f"Reason: assessmentType={job.assessment_type}",
        )

        report = await asyncio.to_thread(
            _execute_with_captured_output, orchestrator, intent, logger
        )
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
        logger.exception("executor", f"Job failed: {exc}", exc)
        job = db.get(JobRecord, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.completed_at = _now()
            job.updated_at = _now()
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
        execution_time_ms = int((time.perf_counter() - started) * 1000)
        job = db.get(JobRecord, job_id)
        input_parameters = None
        if job:
            intent_record = db.get(IntentRecord, job.intent_id)
            if intent_record:
                input_parameters = intent_record.raw_intent_json.get("parameters", {})

        db.merge(
            ExecutionMetadataRecord(
                job_id=job_id,
                agent_name="InTrustRuntimeOrchestrator",
                skill_name=selected_skill.name if selected_skill else None,
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
