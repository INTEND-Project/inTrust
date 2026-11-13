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
- Render one assessment for different audiences (engineer, management,
  compliance, external) from a single canonical result.
- Serve a browser demo page at `/` for submitting intents and reading results
  without `curl`.

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
INTRUST_RENDITION_SUMMARY=1
MIA_INITIATE_URL=http://<mia-host>:<port>/initiate
MIA_RETRIEVE_URL=http://<mia-host>:<port>/retrieve
```

`INTRUST_RENDITION_SUMMARY=0` turns off the per-audience prose summaries. Every
rendition is deterministic and needs nothing from a model, so a deployment
without a reachable LLM still serves reports — it just serves them
without the narrative. Set it off in tests and wherever an LLM call on the read
path is unwanted.

The model is not configured separately. Both LLM calls that bypass the ADK agent
loop — formal-report composition and the prose summaries — read the assessment
agent's own model (the `MODEL` setting in `.env`, read in
`orchestrator/agent.py`), so that setting is the single place a model is
chosen. `RENDITION_SUMMARY_MODEL` overrides it for summaries alone, if the
prose should be written by something other than the model running the
assessment.

`MIA_INITIATE_URL` and `MIA_RETRIEVE_URL` point the `mia-privacy` skill at
the membership-inference (MIA) service. The code contains no default address, so
both must be set before that skill is used; if they are missing, the assessment
fails with an error naming the unset variable. The other skills do not need
them.

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

### Interactive Demo Page

For a quick walkthrough without `curl`, open `http://localhost:8000/` in a
browser. The page is served by the application itself, so it is same-origin with
the API and needs no CORS configuration or separate web server.

It covers the whole submit-then-read loop:

- **Submit an intent** — choose a local JSON intent file (for example one from
  `intents/`). It is shown both as a human-readable summary (id, name, target,
  actor, parameters) and as the full JSON, then posted to `POST /intent`.
- **Store the job** — the returned `jobId` is kept in the browser's
  `localStorage`, so it survives reloads and is there when you come back to read
  the result. Each stored job shows its latest status.
- **Read the result** — fetch `GET /result/{jobId}` for any stored job. A
  **View as** selector re-reads it for a different audience via `?profile=`
  (`technical`, `management`, `compliance`, `external`).
- **Read the JSON comfortably** — both the intent and the result are rendered
  with syntax colouring and per-node code folding (`Expand all` / `Collapse all`,
  or click any `▾` to fold a section), so a large report is easy to navigate.
- **Summary window** — a button opens the prose summary in a separate window with
  its Markdown rendered. It shows `renditionSummary` for the profile currently
  being viewed, labelled with that profile and register, and surfaces any
  warnings attached to it. When no rendition summary is available it falls back
  to `agentSummary`, labelled as the execution narrative rather than an audience
  rendition, so the two are never confused.

The page uses only the public endpoints below; it is a convenience over them,
not a separate interface.

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

### Audience Report Profiles

One assessment produces one canonical `facts` object, and each audience view is
a deterministic projection of it: field selection and aggregation, no second
interpretation of the tool output. Two audiences therefore cannot be given
contradicting results — only the level of detail and the language differ.

The profile is chosen from the intent, not from the query. Declare it
explicitly, or let it follow from who issued the intent:

```json
{
  "intentId": "intent-mia-001",
  "actor": { "role": "CISO", "organization": "Fill GmbH" },
  "reporting": { "profile": "management" }
}
```

`reporting.profile` wins if present; otherwise the issuer's `actor.role` (or
`requestedBy.role`) selects it, and an unrecognised role falls back to
`technical`. The rendition for that profile is stored with the report, so no
query parameter is needed to read it back.

| Profile | Serves | Emphasizes / Omits |
| ------- | ------ | ------------------ |
| `technical` | SecurityAuditor, Developer | Full observations, evidence, and remediation steps. Internal disclosure. |
| `management` | CISO, Management | Verdict, worst case, compliance headline. No observation matrix. MEDIUM severity floor. Confidential. |
| `compliance` | ComplianceOfficer, DPO, Auditor | Obligations evidenced vs not, method and thresholds, per-dimension coverage. Confidential. |
| `external` | Sales, AccountManager | Allowlisted statement only, released for a clean assessment once approved, and dated to expire. External disclosure. |

`reportProfile.resolvedBy` in the response records which rule applied, so a
reader can always tell why their report looks the way it does.

Runnable examples. There is a four-intent set per assessment skill, and within
each set the intents share the same target, parameters, criteria and `intentId`,
so they produce the same canonical facts and differ only in rendition:

```bash
curl -X POST http://localhost:8000/intent \
  -H "Content-Type: application/json" \
  -d @intents/sample_intent_mia_technical.json
```

Each set demonstrates something the others cannot. Pick by what you want to see,
not by skill:

| Set | `intentId` | Shape | What only this set shows |
| --- | --- | --- | --- |
| `sample_intent_mia_*` | `fill` | `parameterSweep` | Reduction by **aggregation** — argmax for management, per-dimension for compliance — and the unconfirmed-metric-semantics disclosure |
| `sample_intent_python_scan_*` | `intent-sec-analysis-002` | `findingList` | Omission by **severity floor**: four LOW findings, all below the MEDIUM floor, so `findings` is empty while `findingsOmitted` is 4 |
| `sample_intent_image_scan_*` | `intent-docker-scan-002` | `findingList` | Omission by **top-N cap**: 25 findings, 5 shown, 20 counted |
| `sample_intent_fs_scan_*` | `intent-fs-scan-003` | `findingList` | The profile mechanism with no reduction at all — 2 findings, `findingsOmitted` 0 in every profile |
| `sample_intent_k8s_scan_*` | `intent-k8s-scan-002` | `findingList` | Misconfiguration findings, and ISO 27001 A.8.27, which no other skill evidences. Needs a reachable cluster; outcome unverified |

Within every set, the four profiles behave as the table above describes. Two
intents stand outside the sets:

| Sample intent | Shows |
| --- | --- |
| `sample_intent_python_scan_external_release.json` | The **only** sample that can produce a *released* external statement — every other external sample demonstrates the gate closing |
| `sample_intent_k8s_scan_external.json` | A gate other than the verdict doing the work: withheld for a missing date and approval even on a clean scan |

The four `*_external.json` intents in the sets narrow their `criteria` to one
entry, which is worth reading against their siblings: with a single resolvable
criterion `regulatoryCoverage.complete` is `true`, and that means every criterion
named was resolved — not that the standard is covered. The four-criteria siblings
resolve to `false` and make the distinction visible.

Re-reading for a different audience is a separate matter from choosing one.
When someone other than the issuer needs the same assessment later — a
compliance officer auditing a report an engineer requested weeks ago — the view
can be rebuilt on read without re-running the tool. Ask by rendition, or by who
is reading:

```bash
curl http://localhost:8000/reportProfiles
curl "http://localhost:8000/result/<job-id>?profile=compliance"
curl "http://localhost:8000/result/<job-id>?role=DPO"
```

`?role=` uses the same role mapping that resolves an intent's own profile from
`actor.role`, so a reader states who they are rather than which rendition they
need — `GET /reportProfiles` lists the roles each profile serves. `?profile=`
wins if both are given, and `reportProfile.resolvedBy` records which form was
used (`reader role=DPO` versus `requested profile=compliance`), so the two
routes to one rendition stay distinguishable afterwards.

An unrecognised role is refused with a `400` rather than falling back to
`technical` the way an intent's own unrecognised `actor.role` does. The fallback
is right at submission time, where the issuer is inside the organisation and
already holds the facts; on a read it would answer `role=Custmoer` with the
fullest internal rendition, handing over evidence and remediation detail on the
strength of a typo.

Either form re-projects from the stored `facts`; neither re-assesses. Re-issuing
the intent instead would run the tool again against a target that may have
changed, altering the facts in order to alter the wording.

A rendition also carries `reportProfile.findingsOmitted` and
`observationReduction`, so whatever a projection dropped stays visible. The
canonical `facts` remain in the response alongside it: a profile is a reading
aid, not an access control.

### Prose Summaries

Each rendition is accompanied by `renditionSummary` — a Markdown narrative for
that audience, in that audience's register.

It is composed **from the rendition, never from `facts`**, and that ordering is
the whole design. The deterministic reduction runs first, so the model writing
the management summary has no access to the findings the management profile
dropped: a summary cannot state what its profile withheld, because the withheld
material is not among its inputs. Consistency between audiences is structural,
the same way it is for the renditions themselves, rather than an instruction a
model is asked to follow.

Generating one narrative from `facts` and reusing it, or generating all four in a
single call, cannot offer that. Compression *is* interpretation — a model handed
the canonical facts and asked for an executive summary has to decide for itself
whether four floor-suppressed LOW findings read as "no significant issues" or as
"four findings below threshold", and nothing constrains it to decide the same way
twice or the same way the technical rendition did.

Summaries are cached per `(job, profile)` and keyed on a fingerprint of the
rendition, so repeated reads of one profile return identical prose while a change
to the projector invalidates it. The fingerprint ignores how the rendition was
asked for: `?role=DPO` and `?profile=compliance` are the same view reached two
ways and share one cached summary. A cache miss costs one LLM call, taken inline.

Two renditions are refused rather than narrated:

- A failed projection — there is nothing to summarise, and prose composed from
  the error would read as an assessment finding.
- A withheld external statement — its entire content is that nothing was
  released, which prose would only soften. External prose therefore exists only
  after the release gate passes, which is also why it is composed on first read
  rather than at submission time.

A **non-conforming** rendition is summarised anyway, with the violation count
attached as a warning on the summary. Withholding it would destroy part of the
evidence of the projection bug the non-conformance indicates — the same reasoning
that keeps the non-conforming rendition in the envelope.

`agentSummary` is a different thing and is retained: it is the agent's own final
text from execution time, written in a technical register for whichever profile
the intent resolved to. It is a record of what the agent said while running, not
an audience rendition, and should not be presented as one.

The summary is a model output, not a derivation. `renditionValidation` checks the
rendition against the SHACL shapes; nothing yet checks the prose against the
rendition it describes, so a summary can still misdescribe material it was
correctly given — the structure bounds that to one profile rather than ruling it
out.

InTrust is a prototype and has no authentication. `?role=` is therefore a
statement by the caller, not an identity, and `disclosureClass` describes how a
rendition is meant to be handled rather than enforcing it — any caller reaching
`GET /result/<job-id>` receives `facts` and `raw` whichever rendition they asked
for. Profiles make a report suit its reader; they do not keep anything from
anyone. That belongs to whatever fronts the service.

### Approve an external release

The `external` profile withholds its statement until a named person has cleared
it, so a clean assessment on its own releases nothing:

```bash
curl -X PUT http://localhost:8000/result/<job-id>/releaseApproval \
  -H "Content-Type: application/json" \
  -d '{"approvedBy": "Release Board", "reference": "CR-1234"}'

curl "http://localhost:8000/result/<job-id>?profile=external"
```

The approval is stored server-side rather than accepted alongside the report
request: an approval a caller can assert in the same call it authorises is not a
control. `GET /result/<job-id>/releaseApproval` reports whether one exists.

Approval is one condition among five, not an override. An approved assessment
that found a problem stays withheld, and every released statement carries
`assessedOn` and `validUntil` — after that date the claim must be re-established
by a fresh assessment, since the component it describes keeps changing while the
artifact does not.

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
- `mia-privacy`: Membership inference privacy assessment of an ML model, run by
  the remote MIA service. Requires `MIA_INITIATE_URL` and `MIA_RETRIEVE_URL`
  (see [Configuration](#configuration)).

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
