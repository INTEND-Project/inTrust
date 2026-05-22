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


class SkillResponse(BaseModel):
    name: str
    description: str
    accepted_parameters: List[str]
    supported_assessment_types: List[str]
