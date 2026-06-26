"""
InTrust Runtime Service — application entry point.

This file creates the FastAPI application, configures logging, and sets up
the startup event handler that initialises the database and loads skills.

To run in development mode:
    uvicorn main:app --reload

To run in production (Docker):
    The Docker entrypoint calls uvicorn directly (see Dockerfile / docker-compose.yml).

Environment variables that affect startup:
    DATABASE_TYPE       sqlite (default) or mysql
    INTRUST_LOG_DIR     directory for log files (default: logs/)
    INTRUST_STORAGE_DIR directory for tool output files (default: storage/)
    GEMINI_API_KEY      required for LLM-based skill selection
"""

from dotenv import load_dotenv

# Load .env before any other imports so that environment variables are
# available when modules read them at import time (e.g. database.py reads
# DATABASE_TYPE at module level).
load_dotenv()

from fastapi import FastAPI

from api.database import database_backend_name, init_db, mark_interrupted_jobs_failed
from api.routes import router
from orchestrator.skill_loader import load_skills
from services.logging_service import app_logger, configure_logging


# Set up JSON-formatted logging to console and log files before the app starts.
configure_logging()

app = FastAPI(
    title="InTrust Runtime Service",
    description="Asynchronous trustworthiness assessment service for TM Forum intents.",
    version="0.1.0",
)


def _startup_banner(skill_names: list[str]) -> str:
    """Build a human-readable startup summary for the log."""
    skills = "\n".join(f" - {name}" for name in skill_names)
    return (
        "===================================\n"
        "InTrust Runtime Initialized\n"
        f"Database backend: {database_backend_name()}\n"
        "Loaded skills:\n"
        f"{skills}\n"
        "API endpoint: http://0.0.0.0:8000\n"
        "==================================="
    )


@app.on_event("startup")
async def startup() -> None:
    """
    Initialise the service when the FastAPI application starts.

    Steps:
    1. Create database tables (if they do not already exist).
    2. Mark any jobs that were interrupted by a previous restart as FAILED.
    3. Load all assessment skills from the skills/ directory.
    4. Log a startup banner listing the database backend and loaded skills.
    """
    init_db()
    mark_interrupted_jobs_failed()
    registry = load_skills()
    app_logger().info(
        _startup_banner([skill.name for skill in registry.list()]),
        extra={"component": "startup"},
    )


# Register all HTTP route handlers (defined in api/routes.py).
app.include_router(router)
