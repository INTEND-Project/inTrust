"""
Structured logging for InTrust.

InTrust uses JSON-formatted log lines so that log entries can be parsed
programmatically (e.g. by log aggregators such as Loki or Elasticsearch).

Logging architecture
--------------------
Every log message is written to three destinations simultaneously:

1. **Console** (stdout) — visible when running the server locally or in a
   Docker container with ``docker logs``.
2. **General log file** (``logs/intrust.log``) — all log levels, for
   persistent local storage.
3. **Error log file** (``logs/errors.log``) — ERROR level only, making it
   easy to check whether anything went wrong without scanning the full log.

For per-job logging there is also a fourth destination:

4. **Database** (``execution_logs`` table) — written by ``JobLogger`` so
   that the execution history of each job can be retrieved via
   ``GET /logs/{job_id}``.

The ``JobLogger`` class is the main interface used by skills and the
orchestrator.  It wraps the standard Python logger and additionally persists
each message to the database.
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

from api.database import BASE_DIR, ExecutionLogRecord, SessionLocal


# Resolve the log directory from an environment variable so it can be
# overridden in Docker without rebuilding the image.
LOG_DIR = BASE_DIR / os.getenv("INTRUST_LOG_DIR", "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    """
    Custom log formatter that produces one JSON object per log line.

    Each line contains at minimum: timestamp, level, component, message.
    Optional fields (job_id, stack_trace) are included only when present.
    The ``component`` field identifies the part of the system that emitted
    the log (e.g. ``"skill.bandit"``, ``"orchestrator"``, ``"api.intent"``).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            # component is injected via the ``extra`` parameter in logger calls.
            # Falls back to the logger name if not provided.
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
    """
    Set up the root InTrust logger with all three output handlers.

    This function is idempotent — calling it multiple times clears and
    re-configures the handlers.  It is called once at application startup
    from ``main.py``.
    """
    root = logging.getLogger("intrust")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    # Prevent log records from bubbling up to the root Python logger, which
    # would cause duplicate output alongside uvicorn's own logging.
    root.propagate = False

    formatter = JsonFormatter()

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "intrust.log", encoding="utf-8"),
    ]
    # The error handler uses a higher threshold so that only ERROR (and above)
    # messages end up in errors.log.
    error_handler = logging.FileHandler(LOG_DIR / "errors.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)

    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def app_logger() -> logging.Logger:
    """
    Return the application-wide InTrust logger.

    If the logger has not been configured yet (e.g. during testing), it is
    configured lazily.  In production, ``configure_logging()`` is called
    explicitly at startup so this lazy path is never taken.
    """
    logger = logging.getLogger("intrust")
    if not logger.handlers:
        configure_logging()
    return logger


class JobLogger:
    """
    A logger bound to a specific assessment job.

    Every message logged through ``JobLogger`` is written to:
    - The application log (console + log files) with the ``job_id`` attached.
    - The ``execution_logs`` database table so it can be retrieved later via
      ``GET /logs/{job_id}``.

    Parameters
    ----------
    job_id : str
        The identifier of the job this logger is associated with.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def log(self, level: str, component: str, message: str) -> None:
        """
        Write a log entry at the given level.

        Parameters
        ----------
        level : str
            Log level string: ``"INFO"``, ``"WARNING"``, or ``"ERROR"``.
        component : str
            The subsystem emitting this message (e.g. ``"skill.bandit"``).
        message : str
            The log message text.
        """
        # Write to the application logger (console + files).
        app_logger().log(
            getattr(logging, level.upper(), logging.INFO),
            message,
            extra={"job_id": self.job_id, "component": component},
        )
        # Also persist to the database for queryable job history.
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
        """Log an informational message."""
        self.log("INFO", component, message)

    def warning(self, component: str, message: str) -> None:
        """Log a warning message."""
        self.log("WARNING", component, message)

    def error(self, component: str, message: str) -> None:
        """Log an error message."""
        self.log("ERROR", component, message)

    def exception(
        self, component: str, message: str, exc: BaseException
    ) -> None:
        """
        Log an exception with its full stack trace.

        The stack trace is included both in the application log (via the
        standard ``exc_info`` mechanism) and in the database log entry.
        """
        stack_trace = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        # Write to the application logger with exc_info so the JSON formatter
        # includes the stack_trace field.
        app_logger().error(
            message,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"job_id": self.job_id, "component": component},
        )
        # Write to the database including the stack trace in the message text
        # so it is visible when querying the execution_logs table directly.
        self.log(
            "ERROR",
            component,
            f"{message}\ntimestamp={datetime.now(timezone.utc).isoformat()}\n"
            f"job_id={self.job_id}\nstack_trace={stack_trace}",
        )
