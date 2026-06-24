# InTrust Runtime Service

InTrust is an asynchronous trustworthiness assessment microservice for TM Forum
intents. It accepts intent payloads over HTTP, selects an assessment skill,
executes the relevant security or trustworthiness tool, stores results, and
exposes logs and metadata for external orchestration systems.

## Capabilities

- Accept TM Forum style intents with `POST /intent`.
- Route assessments dynamically to loaded skills.
- Run supported security assessments asynchronously.
- Persist jobs, intents, results, metadata, and execution logs.
- Support lightweight SQLite development and Dockerized MySQL deployment.
- Expose health, result, log, and skill discovery APIs.

## Database Modes

InTrust chooses its database backend from environment variables.

### Mode A: Local Development

Use this mode for quick local debugging without Docker Compose.

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Default environment:

```env
DATABASE_TYPE=sqlite
INTRUST_STORAGE_DIR=storage
INTRUST_LOG_DIR=logs
SQLITE_DATABASE_FILE=intrust.db
```

The application automatically creates:

```text
storage/intrust.db
```

Tables are initialized automatically at application startup with SQLAlchemy
metadata. No manual migration step is required for the initial runtime schema.

### Mode B: Full Docker Deployment

Use this mode for a production-style local deployment with an API container and
MySQL 8 database container.

```bash
docker compose up --build
```

The Compose stack includes:

- `intrust-api`: FastAPI runtime exposed on port `8000`.
- `intrust-db`: MySQL 8 with a persistent volume.
- `intrust-mysql-data`: database persistence.
- `intrust-logs`: persistent application logs.
- `intrust-storage`: runtime storage for generated artifacts.

Default MySQL configuration:

```env
MYSQL_DATABASE=intrust
MYSQL_USER=intrust
MYSQL_PASSWORD=intrustpass
MYSQL_ROOT_PASSWORD=rootpass
```

The API connects to MySQL using:

```text
mysql+pymysql://intrust:intrustpass@intrust-db:3306/intrust
```

You can override any of these values in `.env`.

## Configuration

Common environment variables:

```env
DATABASE_TYPE=sqlite
INTRUST_STORAGE_DIR=storage
INTRUST_LOG_DIR=logs
SQLITE_DATABASE_FILE=intrust.db
MYSQL_DATABASE=intrust
MYSQL_USER=intrust
MYSQL_PASSWORD=intrustpass
MYSQL_ROOT_PASSWORD=rootpass
```

`DATABASE_URL` may also be set explicitly when an orchestrator needs to provide
the full SQLAlchemy connection string. If it is set, it takes precedence over
the generated SQLite or MySQL URL.

## Startup Diagnostics

On startup, the service prints a structured diagnostic banner to the console and
to `logs/intrust.log`:

```text
===================================
InTrust Runtime Initialized
Database backend: MySQL
Loaded skills:
 - bandit-static-code
 - trivy-docker-image
 - trivy-filesystem
 - trivy-kubernetes
API endpoint: http://0.0.0.0:8000
===================================
```

## Logging

Logs are written simultaneously to:

- Console
- `logs/intrust.log`
- `logs/errors.log`

Runtime logs include:

- Intent reception
- Orchestrator skill decisions
- Skill execution start
- Subprocess command invocation
- Assessment completion
- Exceptions with timestamp, component, job ID, and stack trace

## API Examples

### Health

```bash
curl http://localhost:8000/health
```

Example response:

```json
{
  "status": "healthy",
  "database": "connected",
  "loaded_skills": 4
}
```

### Skill Discovery

```bash
curl http://localhost:8000/skills
```

Returns each skill name, description, accepted parameters, and supported
assessment types.

### Submit Intent

```bash
curl -X POST http://localhost:8000/intent \
  -H "Content-Type: application/json" \
  -d @intents/sample_intent_python_scan.json
```

Example response:

```json
{
  "jobId": "job-...",
  "status": "QUEUED"
}
```

### Get Result

```bash
curl http://localhost:8000/result/<job-id>
```

### Get Logs

```bash
curl http://localhost:8000/logs/<job-id>
```

### List Jobs

```bash
curl http://localhost:8000/jobs
```

## Current Skills

- `bandit-static-code`: Python static security analysis with Bandit.
- `trivy-docker-image`: Docker image vulnerability scanning with Trivy.
- `trivy-filesystem`: Filesystem vulnerability, secret, and misconfiguration scanning.
- `trivy-kubernetes`: Kubernetes cluster scanning with Trivy.

Detailed skill notes are available in `docs/skills/`.

## Portability Notes

InTrust keeps runtime state in database and log/storage volumes. Configuration
is environment-variable driven so the same service can run locally, under Docker
Compose, or later in Kubernetes with externally managed database and volume
resources.
