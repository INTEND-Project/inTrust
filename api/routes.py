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


def _extract_intent_id(intent: Dict[str, Any]) -> str:
    return (
        intent.get("intentId")
        or intent.get("id")
        or intent.get("@id")
        or f"intent-{uuid4()}"
    )


def _extract_assessment_type(intent: Dict[str, Any]) -> str | None:
    params = intent.get("parameters", {})
    return (
        params.get("assessmentType")
        or intent.get("assessmentType")
        or intent.get("name")
        or intent.get("type")
    )


def _job_summary(record: JobRecord) -> JobSummary:
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


@router.post("/intent", response_model=IntentSubmissionResponse)
async def submit_intent(
    intent: Dict[str, Any],
    db: Session = Depends(get_db),
) -> IntentSubmissionResponse:
    if not isinstance(intent, dict) or not intent:
        raise HTTPException(status_code=400, detail="Intent payload must be a JSON object")

    job_id = f"job-{uuid4()}"
    intent_id = _extract_intent_id(intent)
    assessment_type = _extract_assessment_type(intent)

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
    asyncio.create_task(execute_job(job_id))
    return IntentSubmissionResponse(jobId=job_id, status=JobStatus.QUEUED)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
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
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    result = db.get(ResultRecord, job_id)
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
    jobs = db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
    return [_job_summary(job) for job in jobs]


@router.get("/logs/{job_id}", response_model=LogsResponse)
async def get_logs(job_id: str, db: Session = Depends(get_db)) -> LogsResponse:
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    logs = (
        db.query(ExecutionLogRecord)
        .filter(ExecutionLogRecord.job_id == job_id)
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
