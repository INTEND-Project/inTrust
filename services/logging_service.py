import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

from api.database import BASE_DIR, ExecutionLogRecord, SessionLocal


LOG_DIR = BASE_DIR / os.getenv("INTRUST_LOG_DIR", "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "message": record.getMessage(),
        }
        job_id = getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = job_id
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger("intrust")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.propagate = False

    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "intrust.log", encoding="utf-8"),
    ]
    error_handler = logging.FileHandler(LOG_DIR / "errors.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)

    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def app_logger() -> logging.Logger:
    logger = logging.getLogger("intrust")
    if not logger.handlers:
        configure_logging()
    return logger


class JobLogger:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def log(self, level: str, component: str, message: str) -> None:
        app_logger().log(
            getattr(logging, level.upper(), logging.INFO),
            message,
            extra={"job_id": self.job_id, "component": component},
        )
        db = SessionLocal()
        try:
            db.add(
                ExecutionLogRecord(
                    job_id=self.job_id,
                    log_level=level.upper(),
                    component=component,
                    message=message,
                )
            )
            db.commit()
        finally:
            db.close()

    def info(self, component: str, message: str) -> None:
        self.log("INFO", component, message)

    def warning(self, component: str, message: str) -> None:
        self.log("WARNING", component, message)

    def error(self, component: str, message: str) -> None:
        self.log("ERROR", component, message)

    def exception(self, component: str, message: str, exc: BaseException) -> None:
        stack_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        app_logger().error(
            message,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"job_id": self.job_id, "component": component},
        )
        self.log(
            "ERROR",
            component,
            f"{message}\ntimestamp={datetime.now(timezone.utc).isoformat()}\n"
            f"job_id={self.job_id}\nstack_trace={stack_trace}",
        )
