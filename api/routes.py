# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: TMF921 routes for intents and their reports, audience report
#     profiles and re-projection, release approval.
# SPDX-License-Identifier: MIT
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
    if the job is still running.  ``?profile=`` re-renders the report for a
    different audience; every profile is projected from the same stored facts.
    ``?role=`` does the same by naming the reader instead of the rendition,
    resolved through the same role mapping that applies at submission time.

GET /reportProfiles
    Lists the audience profiles a report can be rendered for, what each one
    includes and omits, and which reader roles resolve to it.

PUT /result/{job_id}/releaseApproval
GET /result/{job_id}/releaseApproval
    Record or read the human approval required before an assessment result may
    be released outside the organisation.  Held server-side rather than accepted
    alongside the report request: an approval a caller can assert in the same
    call it authorises is not a control.  Until one is recorded, the external
    profile withholds its statement.

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
from datetime import timezone
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import (
    ExecutionLogRecord,
    ExecutionMetadataRecord,
    IntentRecord,
    JobRecord,
    ReleaseApprovalRecord,
    RenditionSummaryRecord,
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
    ReleaseApprovalRequest,
    ReleaseApprovalResponse,
    ReportProfileResponse,
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


# ---------------------------------------------------------------------------
# Audience projection
# ---------------------------------------------------------------------------

def _approval_for(db: Session | None, job_id: str | None) -> Dict[str, Any] | None:
    """
    Look up the recorded release approval for a job, if there is one.

    Read from the store and never from the request, because an approval a caller
    can assert in the same call it authorises is not a control.  No row means not
    approved, so a missing approval withholds rather than releases.
    """
    if db is None or not job_id:
        return None
    record = db.get(ReleaseApprovalRecord, job_id)
    if record is None:
        return None
    return {
        "state": "approved",
        "approvedBy": record.approved_by,
        "recordedAt": (
            record.recorded_at.isoformat() if record.recorded_at else None
        ),
        "reference": record.reference,
    }


def _assessed_on(job: JobRecord | None) -> str | None:
    """
    The date an external statement's validity is measured from.

    The job's completion time, falling back to its creation time: an expiry has
    to run from when the component was actually looked at, and an assessment
    that never completed has nothing to release anyway.

    Always returned with a UTC offset.  SQLite discards ``tzinfo`` on the way
    out, so the stored value comes back naive while the derived expiry keeps its
    offset — and the shapes compare the two as ``xsd:dateTime``, where mixing
    naive and offset values is not reliably ordered.  Timestamps are written in
    UTC (``services/executor._now``), so labelling them as such loses nothing.
    """
    if job is None:
        return None
    stamp = job.completed_at or job.created_at
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.isoformat()


def _profile_for_reader(
    profile_name: str | None, role: str | None
) -> tuple[str | None, str | None]:
    """
    Resolve what a reader asked for into a profile name, and how it was chosen.

    Two ways to ask, and the difference matters.  ``?profile=`` names a rendition
    directly; ``?role=`` names the audience and lets the same mapping that runs
    at submission time pick the rendition.  A compliance officer re-reading an
    assessment an engineer requested should not have to know that their view is
    called "compliance" — the intent's own issuer never does.

    An unrecognised role is rejected rather than defaulted.  ``resolve_profile``
    falls back to ``technical`` for an intent asserting a role nobody mapped,
    which is right there: the issuer is inside the organisation and already holds
    the facts.  It is wrong here.  A read for ``role=Customer`` is not the same
    request as a read for ``role=Custmoer``, and answering the typo with the
    fullest internal rendition would hand over evidence and remediation detail on
    the strength of a spelling mistake.  Failing loudly costs a round trip; the
    alternative discloses.

    This is not access control, and cannot be: there is no authentication here,
    ``?role=`` is self-asserted, and ``facts`` is returned beside every rendition
    regardless.  A caller who wants the technical view can simply ask for it.  The
    refusal is about what the service *volunteers* — a request naming a role
    nobody mapped has established nothing, and the honest answer to it is a
    question, not the fullest rendition on file.

    ``profile`` wins when both are given, on the same precedence
    ``resolve_profile`` uses: the more specific request is the one the caller was
    more deliberate about.
    """
    if profile_name:
        return profile_name, None

    if role:
        from orchestrator.report_profile import REGISTRY

        profile = REGISTRY.for_role(role)
        # Recorded trimmed, matching how ``for_role`` matched it.  The basis is
        # carried into the rendition and read there by a person, so it should not
        # preserve the caller's stray whitespace.
        role = str(role).strip()
        if profile is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown reader role: {role!r}. No report profile serves "
                    f"it, and defaulting to the fullest rendition for a role "
                    f"the framework does not recognise would disclose more than "
                    f"the request establishes. Pass a known role, or name a "
                    f"profile with ?profile=. "
                    f"See GET /reportProfiles for both."
                ),
            )
        return profile.name, f"reader role={role}"

    return None, None


async def _summary_for(
    db: Session | None,
    job: JobRecord | None,
    rendition: Dict[str, Any],
    profile_name: str,
    validation: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """
    The prose summary for a rendition: from cache, or composed and cached.

    Composed from ``rendition`` and nothing else, which is what stops two
    audiences receiving contradicting narratives of one assessment.  The
    deterministic reduction has already happened by the time this runs, so a
    management summary has no access to the findings the management profile
    dropped — the constraint is structural rather than an instruction to a model.

    Cached per ``(job, profile)`` and keyed on a fingerprint of the rendition, so
    repeated reads of one profile return byte-identical prose while a projector
    change invalidates it.  A cache miss costs one LLM call, taken inline: the
    alternative is returning a placeholder and asking the caller to poll for
    prose, which is a worse trade for a read that already waited on a database.

    A non-conforming rendition is summarised anyway, with the notice attached.
    Withholding the prose would remove part of the evidence of the projection bug
    the non-conformance indicates, and the rendition itself is kept for exactly
    that reason.
    """
    from orchestrator.rendition_summary import (
        rendition_fingerprint,
        summaries_enabled,
        summarise_rendition,
    )
    from orchestrator.report_profile import REGISTRY

    if not summaries_enabled():
        # Checked before the cache read so a deployment with summaries off does no
        # summary work at all on the read path.
        return {
            "status": "SKIPPED",
            "reason": "prose summaries are disabled (INTRUST_RENDITION_SUMMARY)",
        }

    profile = REGISTRY.get(profile_name)
    if profile is None:  # pragma: no cover — _reproject validated it already
        return {"status": "SKIPPED", "reason": f"unknown profile {profile_name!r}"}

    warnings: List[str] = []
    if isinstance(validation, dict) and validation.get("conforms") is False:
        warnings.append(
            f"the rendition this summary describes violates "
            f"{validation.get('violation_count')} SHACL shape constraint(s); "
            f"read it as evidence of a projection problem, not as an assessment "
            f"finding"
        )

    fingerprint = rendition_fingerprint(rendition)
    job_id = job.job_id if job else None

    # Cache hit: same job, same profile, same rendition content.
    if db is not None and job_id:
        cached = db.get(RenditionSummaryRecord, (job_id, profile_name))
        if cached is not None and cached.fingerprint == fingerprint:
            summary = {
                "status": "SUCCESS",
                "markdown": cached.markdown,
                "profile": cached.profile_name,
                "register": cached.register,
                "model": cached.model,
                "generatedAt": (
                    cached.generated_at.isoformat() if cached.generated_at else None
                ),
                "cached": True,
            }
            if cached.warnings:
                summary["warnings"] = cached.warnings
            return summary

    summary = await summarise_rendition(rendition, profile, warnings=warnings or None)
    summary["cached"] = False

    # Store only a composed summary.  A skip is cheap to recompute and a failure
    # should be retried on the next read rather than cached as the answer.
    if db is not None and job_id and summary.get("status") == "SUCCESS":
        try:
            db.merge(
                RenditionSummaryRecord(
                    job_id=job_id,
                    profile_name=profile_name,
                    markdown=summary["markdown"],
                    model=summary.get("model"),
                    register=summary.get("register"),
                    fingerprint=fingerprint,
                    warnings=summary.get("warnings"),
                )
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            # A cache write failure must not cost the caller their summary: it is
            # already composed and correct, and the only loss is that the next
            # read pays for it again.
            db.rollback()
            app_logger().warning(
                f"Could not cache rendition summary for {job_id}/{profile_name}: "
                f"{exc}",
                extra={"job_id": job_id, "component": "api.renditionSummary"},
            )

    return summary


async def _reproject(
    result: Dict[str, Any] | None,
    profile_name: str | None,
    job: JobRecord | None = None,
    db: Session | None = None,
    resolved_by: str | None = None,
) -> Dict[str, Any] | None:
    """
    Replace a stored report's rendition with the one the caller asked for.

    Re-projecting on read rather than storing every rendition keeps one stored
    result per assessment: the canonical ``facts`` are authoritative and each
    rendition is a pure function of them, so a view can always be rebuilt and
    two views can never drift apart.

    Only the ``rendition`` field changes.  ``facts`` stays in the response, so
    a caller receiving a reduced view can still see what it was reduced from —
    a projection is a reading aid here, not an access control.  Withholding
    would be the job of ``disclosureClass``, applied where the caller's
    permissions are known; this service has no authentication and will not gain
    one, so nothing enforces it and every caller can read every rendition.  What
    a profile guarantees is that a report suits its reader and never contradicts
    another reader's, not that anything is kept from anyone.

    ``job`` and ``db`` supply what the external path is gated on: the date the
    assessment was performed, and whether anyone approved releasing it.  Both are
    read here rather than inside the projector, which stays a pure function of
    its arguments so that two reads of one assessment cannot differ.

    ``resolved_by`` overrides the recorded basis for the choice.  A read that
    named a role should say so rather than reporting the profile that role
    resolved to: "reader role=DPO" and "requested profile=compliance" are the
    same rendition arrived at two different ways, and which one happened is
    exactly what a reader asking why their report looks like this needs.
    """
    if not profile_name or not isinstance(result, dict):
        return result

    from orchestrator.report_profile import REGISTRY, project

    facts = result.get("facts")
    if not facts:
        # Skills that do not yet normalise their output have nothing to project
        # from.  Say so rather than returning the previous rendition, which
        # would belong to a different profile than the one requested.  The
        # stored validation goes with it, for the same reason.
        return {
            **result,
            "rendition": {
                "error": (
                    "this assessment has no normalised facts, so no "
                    "audience-specific rendition can be produced"
                )
            },
            "renditionValidation": {
                "status": "SKIPPED",
                "reason": (
                    "no normalised facts, so there is no rendition to validate"
                ),
            },
            "renditionSummary": {
                "status": "SKIPPED",
                "reason": (
                    "no normalised facts, so there is no rendition to summarise"
                ),
            },
        }

    profile = REGISTRY.get(profile_name)
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown report profile: {profile_name!r}. "
                f"Available: {', '.join(sorted(REGISTRY.names()))}"
            ),
        )

    from tools.rendition_validation import validate_rendition

    rendition = project(
        facts,
        profile,
        resolved_by=resolved_by or f"requested profile={profile_name}",
        regulatory_mapping=result.get("regulatoryCoverage") or None,
        provenance=result.get("provenance"),
        assessed_on=_assessed_on(job),
        approval=_approval_for(db, job.job_id if job else None),
    )
    # Re-validate rather than passing the stored verdict through: the stored one
    # was computed for the issuer's own profile, and a conformance result for a
    # technical rendition says nothing about the external statement a caller
    # just asked for.  Validation is cheap and the shapes graph is cached.
    validation = validate_rendition(rendition)
    return {
        **result,
        "rendition": rendition,
        "renditionValidation": validation,
        # Composed from the rendition above — never from ``facts`` — so the prose
        # cannot state what this profile withheld.  Validation runs first so a
        # non-conformance notice can travel with the summary.
        "renditionSummary": await _summary_for(
            db, job, rendition, profile.name, validation
        ),
    }


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


@router.get("/reportProfiles", response_model=List[ReportProfileResponse])
async def list_report_profiles() -> List[ReportProfileResponse]:
    """
    List the audience profiles a report can be rendered for.

    Each entry states which sections it includes, how far numbers are
    disclosed, and which findings it omits, so a caller can see what a
    rendition leaves out before requesting it.  Pass a ``name`` as
    ``?profile=`` to ``GET /result/{job_id}``, or any of its ``roles`` as
    ``?role=`` — this endpoint is where a reader finds which roles are
    recognised, since an unrecognised one is refused rather than defaulted.
    """
    from orchestrator.report_profile import PROFILES

    return [
        ReportProfileResponse(
            name=profile.name,
            description=profile.description,
            roles=list(profile.roles),
            sections=list(profile.sections),
            languageRegister=profile.register,
            numericDisclosure=profile.numeric_disclosure,
            severityFloor=profile.severity_floor,
            sweepProjection=profile.sweep_projection,
            disclosureClass=profile.disclosure_class,
        )
        for profile in PROFILES
    ]


@router.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(
    job_id: str,
    profile: str | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
) -> ResultResponse:
    """
    Return the assessment result for a job.

    While the job is still running, ``result`` will be ``null`` and
    ``status`` will be ``RUNNING``.  Once complete, ``result`` contains the
    full TM Forum-aligned assessment report.  If the job failed, ``error``
    contains the most recent error message from the execution log.

    ``?profile=`` re-renders the report for a different audience —
    ``technical``, ``management``, ``compliance``, or ``external``.  Only the
    ``rendition`` field changes; every profile is projected from the same
    stored ``facts``, so two profiles cannot report different results.  Without
    the parameter the rendition chosen for the intent's own issuer is returned.
    See ``GET /reportProfiles`` for what each one contains.

    ``?role=`` asks by audience instead — ``role=DPO`` rather than
    ``profile=compliance`` — using the same role mapping that resolves an
    intent's own profile from ``actor.role``.  This is the form to reach for
    when someone other than the issuer needs the assessment later: they know
    who they are, not what the rendition is called.  An unrecognised role is a
    400, deliberately, since defaulting it would disclose more than the request
    establishes.  ``profile`` wins if both are given.
    """
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    profile, resolved_by = _profile_for_reader(profile, role)

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
        result=await _reproject(
            result.result_json if result else None,
            profile,
            job=job,
            db=db,
            resolved_by=resolved_by,
        ),
        error=latest_error.message if latest_error else None,
    )


@router.put(
    "/result/{job_id}/releaseApproval", response_model=ReleaseApprovalResponse
)
async def approve_release(
    job_id: str,
    approval: ReleaseApprovalRequest,
    db: Session = Depends(get_db),
) -> ReleaseApprovalResponse:
    """
    Record that a named person has cleared this result for external release.

    Until this is called, ``GET /result/{job_id}?profile=external`` withholds the
    statement and says approval is outstanding.  The approval is stored here
    rather than accepted alongside the report request, because an approval a
    caller can assert in the same call it authorises is no control at all.

    Approving does not itself release anything: the other conditions still
    apply, so an approved assessment that found a problem, or that offers no
    external scope statement, remains withheld.
    """
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    approver = approval.approvedBy.strip()
    if not approver:
        raise HTTPException(
            status_code=400,
            detail=(
                "approvedBy must name the person or role approving release; an "
                "anonymous approval cannot be questioned afterwards"
            ),
        )

    record = db.merge(
        ReleaseApprovalRecord(
            job_id=job_id,
            approved_by=approver,
            reference=approval.reference,
            note=approval.note,
        )
    )
    db.commit()
    db.refresh(record)
    app_logger().info(
        f"External release approved for job {job_id} by {approver}",
        extra={"job_id": job_id, "component": "api.releaseApproval"},
    )
    return ReleaseApprovalResponse(
        jobId=job_id,
        approved=True,
        approvedBy=record.approved_by,
        recordedAt=record.recorded_at,
        reference=record.reference,
        note=record.note,
    )


@router.get(
    "/result/{job_id}/releaseApproval", response_model=ReleaseApprovalResponse
)
async def get_release_approval(
    job_id: str, db: Session = Depends(get_db)
) -> ReleaseApprovalResponse:
    """
    Report whether this result has been cleared for external release.

    An unapproved job answers ``approved: false`` rather than 404: the question
    "has this been approved?" has an answer for every job, and a 404 would
    conflate "not approved" with "no such job".
    """
    if not db.get(JobRecord, job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    record = db.get(ReleaseApprovalRecord, job_id)
    if record is None:
        return ReleaseApprovalResponse(jobId=job_id, approved=False)
    return ReleaseApprovalResponse(
        jobId=job_id,
        approved=True,
        approvedBy=record.approved_by,
        recordedAt=record.recorded_at,
        reference=record.reference,
        note=record.note,
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
    intent_id: str,
    report_id: str,
    profile: str | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
) -> IntentReportResource:
    """
    Return a single IntentReport: the outcome of one evaluation of an intent.

    ``report_id`` is the internal job id.  The report carries a back-reference
    to its parent intent (TMF921 ``IntentRef``) and, once complete, the full
    assessment result.

    ``?profile=`` and ``?role=`` select the audience rendition, as on
    ``GET /result``.
    """
    job = db.get(JobRecord, report_id)
    # Guard against a report id that exists but belongs to a different intent.
    if not job or job.intent_id != intent_id:
        raise HTTPException(
            status_code=404,
            detail=f"Report {report_id!r} not found for intent {intent_id!r}",
        )

    profile, resolved_by = _profile_for_reader(profile, role)

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
        result=await _reproject(
            result.result_json if result else None,
            profile,
            job=job,
            db=db,
            resolved_by=resolved_by,
        ),
        error=latest_error.message if latest_error else None,
    )
