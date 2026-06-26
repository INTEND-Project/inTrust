"""
Database configuration and ORM models for InTrust.

InTrust supports two database backends selected by the ``DATABASE_TYPE``
environment variable:

- ``sqlite`` (default) — a local file-based database, ideal for development
  and single-machine deployments.  No external database server is needed.
- ``mysql`` — a MySQL server, used when running via Docker Compose for
  production-like deployments.

An explicit ``DATABASE_URL`` environment variable overrides both.

The database stores five kinds of records:

- ``JobRecord`` — lifecycle of each assessment job (status, timestamps).
- ``IntentRecord`` — the original intent payload as submitted by the caller.
- ``ResultRecord`` — the final assessment report produced by the skill.
- ``ExecutionLogRecord`` — structured log entries emitted during execution.
- ``ExecutionMetadataRecord`` — environment details (host, Python version,
  tool versions, timing) captured after each job completes.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func


# BASE_DIR is the project root (one level above this file).
BASE_DIR = Path(__file__).resolve().parent.parent

# STORAGE_DIR holds Trivy's raw JSON scan output files.
STORAGE_DIR = BASE_DIR / os.getenv("INTRUST_STORAGE_DIR", "storage")

# Read the desired database backend from the environment.
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite").lower()


def _mysql_url_from_env() -> str:
    """Build a MySQL connection URL from individual environment variables."""
    host = os.getenv("MYSQL_HOST", "intrust-db")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "intrust")
    user = os.getenv("MYSQL_USER", "intrust")
    password = os.getenv("MYSQL_PASSWORD", "intrustpass")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


def _sqlite_url_from_env() -> str:
    """Build a SQLite connection URL, creating the storage directory if needed."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = STORAGE_DIR / os.getenv("SQLITE_DATABASE_FILE", "intrust.db")
    # as_posix() ensures forward slashes on Windows, which SQLite expects.
    return f"sqlite:///{db_path.as_posix()}"


def build_database_url() -> str:
    """
    Determine the database connection URL.

    Priority order:
    1. ``DATABASE_URL`` environment variable (explicit full URL).
    2. ``DATABASE_TYPE=mysql`` → build from individual MySQL env vars.
    3. ``DATABASE_TYPE=sqlite`` (default) → local SQLite file.
    """
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url
    if DATABASE_TYPE == "mysql":
        return _mysql_url_from_env()
    if DATABASE_TYPE == "sqlite":
        return _sqlite_url_from_env()
    raise ValueError(f"Unsupported DATABASE_TYPE: {DATABASE_TYPE!r}")


DATABASE_URL = build_database_url()

# SQLite requires check_same_thread=False because FastAPI's async handlers
# may access the database from different threads.  This is safe here because
# SQLAlchemy sessions are short-lived and not shared across threads.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
    pool_pre_ping=True,  # Reconnect if the connection has gone stale.
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class JobRecord(Base):
    """
    Tracks the lifecycle of one assessment job.

    A job is created when an intent is submitted and progresses through
    QUEUED → RUNNING → COMPLETED (or FAILED).
    """

    __tablename__ = "jobs"

    job_id = Column(String(64), primary_key=True, index=True)
    intent_id = Column(String(255), index=True, nullable=True)
    # assessment_type is extracted from the intent for quick filtering;
    # the full intent is stored separately in IntentRecord.
    assessment_type = Column(String(128), index=True, nullable=True)
    status = Column(String(32), index=True, nullable=False, default="QUEUED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class IntentRecord(Base):
    """
    Stores the original intent payload exactly as submitted by the caller.

    Preserving the raw JSON allows us to re-run assessments or audit exactly
    what was requested, independent of any parsing we do internally.
    """

    __tablename__ = "intents"

    intent_id = Column(String(255), primary_key=True, index=True)
    raw_intent_json = Column(JSON, nullable=False)


class ResultRecord(Base):
    """
    Stores the assessment report produced by a skill.

    ``result_json`` contains the full TM Forum-aligned report envelope.
    ``summary`` and ``recommendation`` are extracted text fields for quick
    display without deserialising the full JSON.
    """

    __tablename__ = "results"

    job_id = Column(String(64), primary_key=True, index=True)
    result_json = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)


class ExecutionLogRecord(Base):
    """
    One structured log entry emitted during job execution.

    Entries are written by ``JobLogger`` and can be retrieved via
    ``GET /logs/{job_id}``.  The ``component`` field identifies which part
    of the system emitted the message (e.g. ``"skill.bandit"``).
    """

    __tablename__ = "execution_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    log_level = Column(String(16), nullable=False)
    component = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)


class ExecutionMetadataRecord(Base):
    """
    Environment and timing information captured after each job completes.

    This record makes results reproducible: we can see exactly which tool
    version produced a given finding, on which host, in how long.
    """

    __tablename__ = "execution_metadata"

    job_id = Column(String(64), primary_key=True, index=True)
    agent_name = Column(String(128), nullable=True)
    skill_name = Column(String(128), nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    host_name = Column(String(255), nullable=True)
    python_version = Column(String(512), nullable=True)
    os_info = Column(String(128), nullable=True)
    tool_versions = Column(JSON, nullable=True)    # e.g. {"bandit": "1.8.0", "trivy": "0.70.0"}
    input_parameters = Column(JSON, nullable=True) # the intent's parameters field
    output_summary = Column(JSON, nullable=True)   # brief summary of the result


def init_db() -> None:
    """Create all database tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)


def database_backend_name() -> str:
    """Return a human-readable name for the active database backend."""
    if DATABASE_URL.startswith("mysql"):
        return "MySQL"
    if DATABASE_URL.startswith("sqlite"):
        return "SQLite"
    return DATABASE_TYPE


def check_database_connection() -> bool:
    """
    Verify that the database is reachable.

    Raises an exception if the connection fails (used by the /health endpoint).
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def mark_interrupted_jobs_failed() -> None:
    """
    Mark any QUEUED or RUNNING jobs as FAILED on startup.

    If the service was restarted while jobs were in progress, those jobs
    will never complete.  This function finds them and marks them as FAILED
    so that the job list does not show stale RUNNING/QUEUED states forever.
    """
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
                        "Job was interrupted by a service restart before completion."
                    ),
                )
            )
        db.commit()
    finally:
        db.close()


def get_db():
    """
    FastAPI dependency that provides a database session for a single request.

    Yields a ``SessionLocal`` instance and ensures it is closed when the
    request is finished, even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
