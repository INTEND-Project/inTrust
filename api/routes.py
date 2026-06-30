"""
HTTP API route handlers for InTrust.

Endpoints
---------
POST /intent
    Submit an assessment request (TM Forum Intent JSON or natural language).
    Returns a job ID immediately; the assessment runs in the background.
    Poll GET /result/{job_id} to check progress.

GET /health
    Returns the service health status, database connectivity, and number of
    loaded skills.  Useful for readiness probes in container orchestration.

GET /skills
    Lists all currently loaded assessment skills with their descriptions and
    accepted parameters.

GET /result/{job_id}
    Returns the assessment result for a completed job, or the current status
    if the job is still running.

GET /jobs
    Returns a summary of all jobs, ordered newest first.

GET /logs/{job_id}
    Returns the structured execution log for a job together with execution
    metadata (timing, tool versions, host information).

TMF921-aligned views (additive; share the same underlying tables)
-----------------------------------------------------------------
GET /intent/{intent_id}
    Returns the intent as a TMF921 Intent resource: its derived lifecycle
    state plus the collection of reports produced for it.

GET /intent/{intent_id}/intentReport
    Returns the collection of IntentReports for an intent (one per evaluation,
    newest first).  Each report's id is the internal job id.

GET /intent/{intent_id}/intentReport/{report_id}
    Returns a single IntentReport (one evaluation outcome) with its result.
"""

import asyncio
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import (
    ExecutionLogRecord,
    ExecutionMetadataRecord,
    IntentRecord,
    JobRecord,
    ResultRecord,
    check_database_connection,
    get_db,
)
from .models import (
    ExecutionLog,
    HealthResponse,
    IntentRef,
    IntentReportRef,
    IntentReportResource,
    IntentResource,
    IntentStateType,
    IntentSubmissionResponse,
    JobStatus,
    JobSummary,
    LogsResponse,
    ResultResponse,
    SkillResponse,
)
from orchestrator.skill_loader import load_skills
from services.executor import execute_job
from services.logging_service import app_logger


router = APIRouter()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_intent_id(intent: Dict[str, Any]) -> str:
    """
    Extract the intent identifier from a TM Forum Intent dictionary.

    TM Forum allows several field names for the identifier.  If none is
    present we generate a random UUID so every intent has a stable ID.
    """
    return (
        intent.get("intentId")
        or intent.get("id")
        or intent.get("@id")
        or f"intent-{uuid4()}"
    )


def _extract_assessment_type(intent: Dict[str, Any]) -> str | None:
    """
    Extract the assessment type hint from a TM Forum Intent dictionary.

    This value is stored on the job record for filtering and display.
    It is NOT used for skill selection (the LLM does that); it is purely
    informational metadata.
    """
    params = intent.get("parameters", {})
    return (
        params.get("assessmentType")
        or intent.get("assessmentType")
        or intent.get("name")
        or intent.get("type")
    )


def _job_summary(record: JobRecord) -> JobSummary:
    """Convert a database JobRecord to the API response model."""
    return JobSummary(
        jobId=record.job_id,
        intentId=record.intent_id,
        assessmentType=record.assessment_type,
        status=record.status,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
        startedAt=record.started_at,
        completedAt=record.completed_at,
    )


# ---------------------------------------------------------------------------
# TMF921 helpers
# ---------------------------------------------------------------------------

# Map our internal job status to the TMF921 intent lifecycle state.
_JOB_STATUS_TO_INTENT_STATE = {
    JobStatus.QUEUED.value: IntentStateType.ACKNOWLEDGED,
    JobStatus.RUNNING.value: IntentStateType.IN_PROGRESS,
    JobStatus.COMPLETED.value: IntentStateType.FULFILLED,
    JobStatus.FAILED.value: IntentStateType.NOT_FULFILLED,
}


def _intent_state(latest_job: JobRecord | None) -> IntentStateType:
    """
    Derive an intent's TMF921 lifecycle state from its most recent report.

    An intent with no reports yet is treated as ``acknowledged``.
    """
    if latest_job is None:
        return IntentStateType.ACKNOWLEDGED
    return _JOB_STATUS_TO_INTENT_STATE.get(
        latest_job.status, IntentStateType.ACKNOWLEDGED
    )


def _report_ref(job: JobRecord) -> IntentReportRef:
    """Build a lightweight IntentReport reference for a collection listing."""
    return IntentReportRef(
        id=job.job_id,
        href=f"/intent/{job.intent_id}/intentReport/{job.job_id}",
        state=job.status,
        createdAt=job.created_at,
        completedAt=job.completed_at,
    )


def _intent_jobs(db: Session, intent_id: str) -> List[JobRecord]:
    """Return all jobs (reports) for an intent, newest first."""
    return (
        db.query(JobRecord)
        .filter(JobRecord.intent_id == intent_id)
        .order_by(JobRecord.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.post("/intent", response_model=IntentSubmissionResponse)
async def submit_intent(
    intent: Dict[str, Any],
    db: Session = Depends(get_db),
) -> IntentSubmissionResponse:
    """
    Submit an assessment request and receive a job ID.

    The intent is stored in the database and a background task is launched
    immediately.  This endpoint returns as soon as the job is queued —
    it does NOT wait for the assessment to finish.

    The caller should poll ``GET /result/{jobId}`` to check for completion.

    The intent body may be:
    - A TM Forum Intent JSON object (structured).
    - Any JSON object describing the assessment informally.
    The LLM will interpret both forms and select the appropriate skill.
    """
    if not isinstance(intent, dict) or not intent:
        raise HTTPException(status_code=400, detail="Intent payload must be a non-empty JSON object")

    job_id = f"job-{uuid4()}"
    intent_id = _extract_intent_id(intent)
    assessment_type = _extract_assessment_type(intent)

    # Persist the intent payload and create the job record before launching
    # the background task, so the executor can find them in the database.
    db.merge(IntentRecord(intent_id=intent_id, raw_intent_json=intent))
    db.add(
        JobRecord(
            job_id=job_id,
            intent_id=intent_id,
            assessment_type=assessment_type,
            status=JobStatus.QUEUED.value,
        )
    )
    db.commit()

    app_logger().info(
        "[Intent Received]\n"
        f"intent_id={intent_id}\n"
        f"assessment_type={assessment_type}",
        extra={"job_id": job_id, "component": "api.intent"},
    )

    # Launch the assessment as a background asyncio task.
    # create_task() schedules the coroutine for execution on the current event
    # loop and returns immediately — the HTTP response is sent before the
    # assessment begins.
    asyncio.create_task(execute_job(job_id))

    return IntentSubmissionResponse(jobId=job_id, status=JobStatus.QUEUED)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Return the current health status of the service.

    Checks database connectivity and counts the number of loaded skills.
    Returns HTTP 200 in all cases; inspect the ``status`` field to determine
    whether the service is healthy.
    """
    try:
        check_database_connection()
        database_status = "connected"
        status = "healthy"
    except Exception as exc:
        app_logger().error(
            f"Health check database failure: {exc}",
            exc_info=True,
            extra={"component": "api.health"},
        )
        database_status = "disconnected"
        status = "unhealthy"

    loaded_skills = len(load_skills().list())
    return HealthResponse(
        status=status,
        database=database_status,
        loaded_skills=loaded_skills,
    )


@router.get("/skills", response_model=List[SkillResponse])
async def list_skills() -> List[SkillResponse]:
    """
    List all currently loaded assessment skills.

    Returns the name, description, accepted parameters, and associated
    assessment-type keywords for each skill.  Useful for understanding what
    kinds of assessments InTrust can perform.
    """
    return [
        SkillResponse(
            name=skill.name,
            description=skill.description,
            accepted_parameters=skill.accepted_parameters,
            supported_assessment_types=skill.assessment_types,
        )
        for skill in load_skills().list()
    ]


@router.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(job_id: str, db: Session = Depends(get_db)) -> ResultResponse:
    """
    Return the assessment result for a job.

    While the job is still running, ``result`` will be ``null`` and
    ``status`` will be ``RUNNING``.  Once complete, ``result`` contains the
    full TM Forum-aligned assessment report.  If the job failed, ``error``
    contains the most recent error message from the execution log.
    """
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    result = db.get(ResultRecord, job_id)
    # Surface the most recent error log entry so callers do not have to
    # fetch the full logs just to see what went wrong.
    latest_error = (
        db.query(ExecutionLogRecord)
        .filter(
            ExecutionLogRecord.job_id == job_id,
            ExecutionLogRecord.log_level == "ERROR",
        )
        .order_by(ExecutionLogRecord.timestamp.desc())
        .first()
    )
    return ResultResponse(
        jobId=job_id,
        status=job.status,
        result=result.result_json if result else None,
        error=latest_error.message if latest_error else None,
    )


@router.get("/jobs", response_model=List[JobSummary])
async def list_jobs(db: Session = Depends(get_db)) -> List[JobSummary]:
    """
    Return a summary of all assessment jobs, newest first.

    Useful for monitoring and debugging.  For the full result of a specific
    job, use ``GET /result/{job_id}``.
    """
    jobs = db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
    return [_job_summary(job) for job in jobs]


@router.get("/logs/{job_id}", response_model=LogsResponse)
async def get_logs(job_id: str, db: Session = Depends(get_db)) -> LogsResponse:
    """
    Return the structured execution log and metadata for a job.

    The response includes:
    - ``logs``: all log entries in chronological order.
    - ``metadata``: environment details (host, Python version, tool versions,
      timing, which skill was selected).
    - ``errors``: just the ERROR-level log messages, for quick scanning.
    - ``warnings``: just the WARNING-level log messages.
    """
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    logs = (
        db.query(ExecutionLogRecord)
        .filter(ExecutionLogRecord.job_id == job_id)
        # Order by timestamp first, then by log_id to break ties within the
        # same second (database timestamps may have limited precision).
        .order_by(ExecutionLogRecord.timestamp.asc(), ExecutionLogRecord.log_id.asc())
        .all()
    )
    metadata = db.get(ExecutionMetadataRecord, job_id)
    log_items = [
        ExecutionLog(
            timestamp=log.timestamp,
            level=log.log_level,
            component=log.component,
            message=log.message,
        )
        for log in logs
    ]

    return LogsResponse(
        jobId=job_id,
        logs=log_items,
        metadata={
            "agentUsed": metadata.agent_name,
            "skillUsed": metadata.skill_name,
            "executionDurationMs": metadata.execution_time_ms,
            "hostName": metadata.host_name,
            "pythonVersion": metadata.python_version,
            "osInfo": metadata.os_info,
            "toolVersions": metadata.tool_versions,
            "inputParameters": metadata.input_parameters,
            "outputSummary": metadata.output_summary,
        }
        if metadata
        else None,
        errors=[log.message for log in logs if log.log_level == "ERROR"],
        warnings=[log.message for log in logs if log.log_level == "WARNING"],
    )


# ---------------------------------------------------------------------------
# TMF921-aligned route handlers
# ---------------------------------------------------------------------------

@router.get("/intent/{intent_id}", response_model=IntentResource)
async def get_intent(intent_id: str, db: Session = Depends(get_db)) -> IntentResource:
    """
    Return an intent as a TMF921 Intent resource.

    The intent's ``state`` is derived from its most recent report, and
    ``intentReport`` lists every report produced for it (newest first).
    Reflects TMF921's one-intent-to-many-reports model.
    """
    intent_record = db.get(IntentRecord, intent_id)
    if not intent_record:
        raise HTTPException(status_code=404, detail=f"Intent not found: {intent_id}")

    jobs = _intent_jobs(db, intent_id)
    # assessment_type is the same across an intent's jobs; take it from the
    # most recent one if available.
    assessment_type = jobs[0].assessment_type if jobs else None

    return IntentResource(
        id=intent_id,
        href=f"/intent/{intent_id}",
        state=_intent_state(jobs[0] if jobs else None),
        assessmentType=assessment_type,
        expression=intent_record.raw_intent_json,
        intentReport=[_report_ref(job) for job in jobs],
    )


@router.get(
    "/intent/{intent_id}/intentReport",
    response_model=List[IntentReportRef],
)
async def list_intent_reports(
    intent_id: str, db: Session = Depends(get_db)
) -> List[IntentReportRef]:
    """
    Return the collection of IntentReports for an intent, newest first.

    Each report corresponds to one evaluation (one internal job).  Returns an
    empty list if the intent exists but has not been evaluated yet; 404 if the
    intent itself is unknown.
    """
    if not db.get(IntentRecord, intent_id):
        raise HTTPException(status_code=404, detail=f"Intent not found: {intent_id}")

    return [_report_ref(job) for job in _intent_jobs(db, intent_id)]


@router.get(
    "/intent/{intent_id}/intentReport/{report_id}",
    response_model=IntentReportResource,
)
async def get_intent_report(
    intent_id: str, report_id: str, db: Session = Depends(get_db)
) -> IntentReportResource:
    """
    Return a single IntentReport: the outcome of one evaluation of an intent.

    ``report_id`` is the internal job id.  The report carries a back-reference
    to its parent intent (TMF921 ``IntentRef``) and, once complete, the full
    assessment result.
    """
    job = db.get(JobRecord, report_id)
    # Guard against a report id that exists but belongs to a different intent.
    if not job or job.intent_id != intent_id:
        raise HTTPException(
            status_code=404,
            detail=f"Report {report_id!r} not found for intent {intent_id!r}",
        )

    result = db.get(ResultRecord, report_id)
    latest_error = (
        db.query(ExecutionLogRecord)
        .filter(
            ExecutionLogRecord.job_id == report_id,
            ExecutionLogRecord.log_level == "ERROR",
        )
        .order_by(ExecutionLogRecord.timestamp.desc())
        .first()
    )

    return IntentReportResource(
        id=report_id,
        href=f"/intent/{intent_id}/intentReport/{report_id}",
        intent=IntentRef(id=intent_id, href=f"/intent/{intent_id}"),
        state=job.status,
        createdAt=job.created_at,
        startedAt=job.started_at,
        completedAt=job.completed_at,
        result=result.result_json if result else None,
        error=latest_error.message if latest_error else None,
    )
