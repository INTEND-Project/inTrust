from api.database import ExecutionLogRecord, SessionLocal


class JobLogger:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def log(self, level: str, component: str, message: str) -> None:
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
