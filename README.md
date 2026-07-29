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
- Expose intents and their evaluation reports as TMF921-aligned resources.

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
 - formal-intent-generation
 - formal-intent-validation
 - formal-report-generation
 - formal-report-validation
 - trivy-filesystem
 - trivy-docker-image
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

The full API is self-documented at `http://localhost:8000/docs` (Swagger UI)
and `http://localhost:8000/openapi.json`.

### Health

```bash
curl http://localhost:8000/health
```

Example response:

```json
{
  "status": "healthy",
  "database": "connected",
  "loaded_skills": 8
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

### Intent and Report Views (TMF921)

The endpoints above are job-centric. The same data is also exposed in the
TM Forum Intent Management (TMF921) shape, where one long-lived `Intent` holds
many `IntentReport` resources — one per evaluation. No extra tables are
involved; these are additive views over the same records, and a report's `id`
is the internal job ID.

#### Get Intent

```bash
curl http://localhost:8000/intent/intent-sec-analysis-001
```

Example response:

```json
{
  "id": "intent-sec-analysis-001",
  "href": "/intent/intent-sec-analysis-001",
  "state": "fulfilled",
  "assessmentType": "static_code_analysis",
  "expression": { "intentId": "intent-sec-analysis-001", "...": "original submitted payload" },
  "intentReport": [
    {
      "id": "job-...",
      "href": "/intent/intent-sec-analysis-001/intentReport/job-...",
      "state": "COMPLETED",
      "createdAt": "2025-10-24T14:35:00Z",
      "completedAt": "2025-10-24T14:35:12Z"
    }
  ]
}
```

`state` is derived from the most recent report, not stored:

| Job status  | Intent state   |
| ----------- | -------------- |
| `QUEUED`    | `acknowledged` |
| `RUNNING`   | `inProgress`   |
| `COMPLETED` | `fulfilled`    |
| `FAILED`    | `notFulfilled` |

An intent with no reports yet is `acknowledged`.

#### List Intent Reports

```bash
curl http://localhost:8000/intent/<intent-id>/intentReport
```

Returns every report for the intent, newest first. Empty list if the intent
exists but has not been evaluated; `404` if the intent is unknown.

#### Get a Single Intent Report

```bash
curl http://localhost:8000/intent/<intent-id>/intentReport/<job-id>
```

Returns one evaluation outcome with the full result, plus a back-reference to
its parent intent. Returns `404` if the report belongs to a different intent.

## Current Skills

### Assessment Skills

These execute a security or trustworthiness tool and return its findings.

- `bandit-static-code`: Python static security analysis with Bandit.
- `trivy-docker-image`: Docker image vulnerability scanning with Trivy.
- `trivy-filesystem`: Filesystem vulnerability, secret, and misconfiguration scanning.
- `trivy-kubernetes`: Kubernetes cluster scanning with Trivy.

### Formal Intent and Report Skills

These do **not** run an assessment. They support authoring and checking TM Forum
documents against the InTrust ontology (`docs/skills/ontology/intrust.ttl`).
The generation skills return ontology vocabulary — classes and properties — that
the agent uses to compose a grounded document in its next turn; the validation
skills check a finished document against the InTrust SHACL shapes.

| Skill | Parameter | Purpose |
| ----- | --------- | ------- |
| `formal-intent-generation` | `description` | Returns the ontology vocabulary needed to compose a formal TM Forum intent from a natural-language description. |
| `formal-intent-validation` | `intent` | Validates an intent against the InTrust SHACL shapes. |
| `formal-report-generation` | `reportInput` | Returns the ontology vocabulary needed to compose a TM Forum assessment report (`tmfIntentReport.v1`) from a raw result. |
| `formal-report-validation` | `report` | Validates an assessment report against the InTrust SHACL shapes. |

The two validation skills accept either a JSON document or a Turtle (RDF)
serialization — the form is detected from the payload — and both return
`conforms`, `violation_count`, and `violations`.

`formal-report-generation` needs both the original intent and the raw result, so
its `reportInput` must be a JSON object:

```json
{ "intent": { "...": "the original intent" }, "raw_result": { "...": "the assessment output" } }
```

Together these compose a generate → author → validate loop: generation supplies
the vocabulary, the agent writes the document, validation confirms conformance
before the document is returned.

Detailed skill notes are available in `docs/skills/`.

## Portability Notes

InTrust keeps runtime state in database and log/storage volumes. Configuration
is environment-variable driven so the same service can run locally, under Docker
Compose, or later in Kubernetes with externally managed database and volume
resources.
