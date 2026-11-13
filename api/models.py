# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: TMF921-aligned intent and intent-report resources, release-
#     approval and report-profile models.
# SPDX-License-Identifier: MIT
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


class ReleaseApprovalRequest(BaseModel):
    """
    A request to clear one assessment result for release outside the company.

    ``approvedBy`` is required and unvalidated.  InTrust has no identity system,
    so this records an unverified name that an audit can question afterwards;
    checking it against nothing would only look like verification.  Whatever
    fronts this endpoint is what should establish who is calling.
    """

    approvedBy: str
    reference: Optional[str] = None
    note: Optional[str] = None


class ReleaseApprovalResponse(BaseModel):
    """The recorded approval, or its absence."""

    jobId: str
    approved: bool
    approvedBy: Optional[str] = None
    recordedAt: Optional[datetime] = None
    reference: Optional[str] = None
    note: Optional[str] = None


class SkillResponse(BaseModel):
    name: str
    description: str
    accepted_parameters: List[str]
    supported_assessment_types: List[str]


class ReportProfileResponse(BaseModel):
    """
    One audience's report profile, as advertised by ``GET /reportProfiles``.

    Exposed so a caller can tell what a rendition contains *and* what it
    leaves out before requesting it — a reduced report is only trustworthy if
    its reductions are discoverable.
    """

    name: str
    description: str
    roles: List[str]
    sections: List[str]
    # Named ``languageRegister`` rather than ``register``, which shadows a
    # pydantic BaseModel attribute.
    languageRegister: str
    numericDisclosure: str
    # ``None`` where the profile carries no findings or no observations.
    severityFloor: Optional[str]
    sweepProjection: Optional[str]
    disclosureClass: str
