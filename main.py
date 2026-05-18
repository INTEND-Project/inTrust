from fastapi import FastAPI
from dotenv import load_dotenv

from api.database import init_db, mark_interrupted_jobs_failed
from api.routes import router


load_dotenv()

app = FastAPI(
    title="InTrust Runtime Service",
    description="Asynchronous trustworthiness assessment service for TM Forum intents.",
    version="0.1.0",
)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    mark_interrupted_jobs_failed()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
