from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from api.database import database_backend_name, init_db, mark_interrupted_jobs_failed
from api.routes import router
from orchestrator.skill_loader import load_skills
from services.logging_service import app_logger, configure_logging


configure_logging()

app = FastAPI(
    title="InTrust Runtime Service",
    description="Asynchronous trustworthiness assessment service for TM Forum intents.",
    version="0.1.0",
)


def _startup_banner(skill_names: list[str]) -> str:
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
    init_db()
    mark_interrupted_jobs_failed()
    registry = load_skills()
    app_logger().info(
        _startup_banner([skill.name for skill in registry.list()]),
        extra={"component": "startup"},
    )


app.include_router(router)
