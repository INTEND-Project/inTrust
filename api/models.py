from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IntentSubmissionResponse(BaseModel):
    jobId: str
    status: JobStatus


class JobSummary(BaseModel):
    jobId: str
    intentId: Optional[str] = None
    assessmentType: Optional[str] = None
    status: JobStatus
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    startedAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None


class ResultResponse(BaseModel):
    jobId: str
    status: JobStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionLog(BaseModel):
    timestamp: Optional[datetime] = None
    level: str
    component: str
    message: str


class LogsResponse(BaseModel):
    jobId: str
    logs: List[ExecutionLog] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    database: str
    loaded_skills: int


# ---------------------------------------------------------------------------
# TMF921-aligned resources
#
# TM Forum Intent Management (TMF921) models the request as a long-lived
# ``Intent`` resource and each evaluation outcome as an ``IntentReport``
# nested underneath it (one intent -> many reports).  These models expose our
# existing tables in that shape: an Intent is an IntentRecord, and each report
# is a JobRecord/ResultRecord pair whose internal ``job_id`` serves as the
# report identifier.
# ---------------------------------------------------------------------------

class IntentStateType(str, Enum):
    """
    Lifecycle states of an intent, mirroring TMF921's ``IntentStateType``.

    Derived from the underlying job status (see ``_intent_state`` in routes).
    """

    ACKNOWLEDGED = "acknowledged"   # accepted, not yet evaluated (QUEUED)
    IN_PROGRESS = "inProgress"      # evaluation running (RUNNING)
    FULFILLED = "fulfilled"         # evaluation completed (COMPLETED)
    NOT_FULFILLED = "notFulfilled"  # evaluation failed (FAILED)


class IntentReportRef(BaseModel):
    """A lightweight reference to an IntentReport, used in collections."""

    id: str
    href: str
    state: JobStatus
    createdAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None


class IntentRef(BaseModel):
    """A back-reference from a report to its parent intent."""

    id: str
    href: str


class IntentResource(BaseModel):
    """
    A TMF921-style Intent resource.

    ``state`` is the intent's overall lifecycle state, derived from its most
    recent report.  ``intentReport`` lists every report produced for it.
    """

    id: str
    href: str
    state: IntentStateType
    assessmentType: Optional[str] = None
    expression: Dict[str, Any] = Field(default_factory=dict)
    intentReport: List[IntentReportRef] = Field(default_factory=list)


class IntentReportResource(BaseModel):
    """A TMF921-style IntentReport resource (one evaluation of an intent)."""

    id: str
    href: str
    intent: IntentRef
    state: JobStatus
    createdAt: Optional[datetime] = None
    startedAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SkillResponse(BaseModel):
    name: str
    description: str
    accepted_parameters: List[str]
    supported_assessment_types: List[str]
