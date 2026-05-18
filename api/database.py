import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / os.getenv("INTRUST_STORAGE_DIR", "storage")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{(STORAGE_DIR / 'intrust.db').as_posix()}"
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, index=True)
    intent_id = Column(String, index=True, nullable=True)
    assessment_type = Column(String, index=True, nullable=True)
    status = Column(String, index=True, nullable=False, default="QUEUED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class IntentRecord(Base):
    __tablename__ = "intents"

    intent_id = Column(String, primary_key=True, index=True)
    raw_intent_json = Column(JSON, nullable=False)


class ResultRecord(Base):
    __tablename__ = "results"

    job_id = Column(String, primary_key=True, index=True)
    result_json = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)


class ExecutionLogRecord(Base):
    __tablename__ = "execution_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    log_level = Column(String, nullable=False)
    component = Column(String, nullable=False)
    message = Column(Text, nullable=False)


class ExecutionMetadataRecord(Base):
    __tablename__ = "execution_metadata"

    job_id = Column(String, primary_key=True, index=True)
    agent_name = Column(String, nullable=True)
    skill_name = Column(String, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    host_name = Column(String, nullable=True)
    python_version = Column(String, nullable=True)
    os_info = Column(String, nullable=True)
    tool_versions = Column(JSON, nullable=True)
    input_parameters = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def mark_interrupted_jobs_failed() -> None:
    db = SessionLocal()
    try:
        interrupted = (
            db.query(JobRecord)
            .filter(JobRecord.status.in_(["QUEUED", "RUNNING"]))
            .all()
        )
        for job in interrupted:
            job.status = "FAILED"
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            db.add(
                ExecutionLogRecord(
                    job_id=job.job_id,
                    log_level="ERROR",
                    component="startup",
                    message=(
                        "Job was interrupted by a service restart before "
                        "completion."
                    ),
                )
            )
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
