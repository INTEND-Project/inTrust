# InTrust Architecture Benchmark

A reproducible benchmarking framework comparing two Google ADK architectural
styles for intent-driven trustworthiness assessment, using InTrust as the
implementation platform:

| | Architecture A — Multi-agent | Architecture B — Single agent + skills |
|---|---|---|
| Orchestrator | 1 root `LlmAgent`, no tools | 1 `LlmAgent` with all skills as tools |
| Downstream | 1 specialist `LlmAgent` per assessment (own LLM instance, own prompt, one tool) | — |
| Routing | ADK `transfer_to_agent` delegation | LLM tool selection |
| LLM calls per run | 3 (route → tool call → summary) | 2 (tool call → summary) |

Everything else — intents, prompts, assessment tools, inputs, ADK version,
hardware — is identical.  The orchestration architecture is the **only
independent variable**.

The benchmark code lives entirely in this `benchmark/` package; the
production InTrust service is not modified and keeps working as before.

---

## 0. Hardware requirements

The full experiment matrix uses 0.8B–27B parameter models and is intended
for a machine with a **GPU** (≥ 24 GB VRAM fits the largest model,
qwen3.5:27b at ~17 GB Q4 — e.g. an NVIDIA A30).  On a CPU-only laptop
these models generate a few tokens per second and a single run can take
many minutes.

For CPU-only machines, use the **pilot configuration**
([`config.pilot.toml`](config.pilot.toml)): tiny models (0.6B–1.7B), 1
warm-up + 3 measured runs, the two infrastructure-free scenarios.  It
exercises the complete pipeline end-to-end and verifies your setup before
the real campaign:

```bash
ollama pull qwen3:0.6b && ollama pull qwen3:1.7b
ollama pull llama3.2:1b && ollama pull gemma3:1b

python -m benchmark.run_benchmark --config benchmark/config.pilot.toml
```

Note on thinking models: qwen3 (and other reasoning models) generate
hundreds of hidden "thinking" tokens per step by default.  The shipped
configs disable this (`think = false` under `[provider.model_kwargs]`) so
runs measure the plain agentic flow; this is part of the recorded
methodology (the full config is echoed into every result file).  Re-enable
it deliberately if reasoning behaviour is itself under study.

---

## 1. Installation

From the repository root (Python 3.11+ required; the repo venv already has
the production dependencies):

```bash
# Activate the project venv first, then:
pip install -r benchmark/requirements.txt
```

This installs `google-adk[extensions]` (which brings `litellm`, needed to
talk to Ollama), `psutil` (CPU/memory sampling) and `matplotlib` (figures).

### Install Ollama and pull the models

Install Ollama from <https://ollama.com/download> and make sure the server
is running (`ollama serve`, default URL `http://localhost:11434`).

Pull the models used by the two experiments:

```bash
# Experiment 1 — family comparison
# (qwen3.5 and deepseek-r1 require a recent Ollama — see the user-local
# Ollama instructions in the Slurm section)
ollama pull qwen3.5:9b
ollama pull llama3.1:8b
ollama pull orieg/gemma3-tools:12b-ft-v2
ollama pull deepseek-r1:8b

# Experiment 2 — qwen3.5 scaling study (qwen3.5:9b already pulled above).
# qwen3.5:35b (~24 GB) and 122b (~81 GB) are excluded — they exceed a
# 24 GB GPU once the KV cache is added.
ollama pull qwen3.5:0.8b
ollama pull qwen3.5:2b
ollama pull qwen3.5:4b
ollama pull qwen3.5:27b
```

Note: manual pulling is only needed when you run the benchmark yourself
against an already-running Ollama server.  The Slurm campaign job
(`benchmark/slurm/run_campaign.job`) pulls the selected experiment's
models automatically before the campaign starts — Ollama does **not**
auto-download models on inference requests.

### One-time scenario preparation

- **Bandit / Trivy filesystem scans** need nothing: they scan frozen
  inputs committed to the repository.  Bandit targets are five small
  Python modules with distinct known findings
  (`benchmark/data/bandit_targets/target_{1..5}/`); Trivy filesystem
  targets are five tiny projects, each just a `requirements.txt` with
  pinned known-CVE package versions
  (`benchmark/data/fs_targets/project_{1..5}/`) so a scan takes seconds.
  Trivy downloads its vulnerability DB on first use — warm-up runs absorb
  this, or pre-cache it with `trivy image --download-db-only` (same DB).
- **Trivy Docker image scan**: pull the pinned image once and pre-download
  the Trivy vulnerability database so neither download pollutes the
  measured timings:

  ```bash
  docker pull python:3.11-slim
  trivy image --download-db-only
  ```

- **Trivy Kubernetes scan** (disabled by default): requires a live cluster
  reachable through your kubeconfig; enable it in the config file.

**Model requirement — native tool calling.**  Both architectures rely on
Ollama's function-calling API, so every benchmark model must have the
`tools` capability: `ollama show <tag>` must list `tools` under
Capabilities.  Models without it (e.g. stock `gemma3`, `phi4` at the time
of writing) are rejected by the server before generation and score 0% —
they cannot participate in either architecture.  The Gemma family entry
is therefore the community build `orieg/gemma3-tools` (QLoRA fine-tune
for function calling — methodology footnote: not stock Gemma).  The
DeepSeek entry is stock `deepseek-r1`, but it **requires a recent
Ollama** — old servers reject it with "does not support tools" (see the
user-local Ollama instructions in the Slurm section); the same applies to
the qwen3.5 family.  qwen3.5 and deepseek-r1 are thinking-capable models
run with `think = false` — part of the recorded methodology.

---

## 2. Configuration

All benchmark parameters live in [`config.default.toml`](config.default.toml).
To change anything, copy the file and pass your copy on the command line —
no code changes are ever needed:

```bash
cp benchmark/config.default.toml my_config.toml
# edit my_config.toml ...
python -m benchmark.run_benchmark --config my_config.toml
```

Key settings:

| Setting | Default | Meaning |
|---|---|---|
| `warmup_runs` | 5 | unrecorded runs before measurement (model loading, caches) |
| `measured_runs` | 30 | recorded runs per (architecture × model × scenario) cell |
| `seed` | 42 | framework-side random seed (run ordering; LLM sampling is server-side) |
| `run_timeout_sec` | 600 | a run exceeding this is recorded as failed |
| `ollama_api_base` | `http://localhost:11434` | Ollama server URL |
| `[provider].request_timeout_sec` | 300 | client-side timeout for one LLM request |
| `[provider.model_kwargs]` | `think=false`, `num_predict=1024`, `num_ctx=8192`, `temperature=0` | generation settings forwarded to LiteLLM/Ollama; part of the recorded methodology (temperature 0 = greedy decoding for reproducibility) |
| `[experiments.*].models` | see file | model list per experiment (LiteLLM `ollama_chat/<name>` strings) |
| `[experiments.*].concurrency_levels` | 1 / 1,5,10,20 | throughput mode levels |
| `[scenarios]` | bandit + trivy fs on | enable/disable individual assessment scenarios |

**Intent variants.**  Each enabled scenario ships **five frozen intent
variants** (different assessment targets, varied TM Forum phrasing) under
`benchmark/data/intents/`; runs rotate through them (`run_idx % 5`, so 30
measured runs = 6 per variant, recorded in the `intent_variant` CSV
column).  This matters because the benchmark decodes greedily
(`temperature = 0`): repeated runs of a single frozen intent are near
deterministic, so per-cell routing accuracy would be one routing decision
observed 30 times.  Five variants make routing accuracy a robustness
measure across intent formulations — and since each variant has a distinct
expected finding set, results also verify the correct target was scanned.
Both architectures always see the identical variant set.

---

## 3. Running the experiments

Always run from the **repository root**.

```bash
# Everything (both experiments, full grid):
python -m benchmark.run_benchmark

# One experiment:
python -m benchmark.run_benchmark --experiment family_comparison
python -m benchmark.run_benchmark --experiment scaling_study
```

Each execution gets a unique run ID (e.g.
`family_comparison_20260703-101530_ab12cd34`) and writes:

```
results/
├── family_comparison/
│   ├── raw/       <run_id>.json  (full records incl. event timelines)
│   │              <run_id>.csv   (flat, one row per measured run — plot-ready)
│   │              <run_id>_throughput.csv
│   ├── plots/     latency_boxplot.png, cpu_usage.png, memory_usage.png,
│   │              token_usage.png, throughput.png
│   ├── latex/     latency.tex, cpu.tex, memory.tex, tokens.tex,
│   │              routing.tex, throughput.tex
│   └── summary.md
├── scaling_study/  (same layout)
└── logs/          <run_id>.jsonl  (structured per-run log)
```

Figures and LaTeX tables are generated automatically after each run.

### Quick verification (before a long campaign)

```bash
# Full pipeline WITHOUT Ollama (synthetic metrics — checks all wiring):
python -m benchmark.run_benchmark --dry-run --runs 3 --warmup 1

# One real run against the smallest model:
python -m benchmark.run_benchmark --experiment scaling_study \
    --model ollama_chat/qwen3.5:0.8b --scenario bandit_static_code \
    --runs 1 --warmup 0
```

---

## 3b. Running on a Slurm cluster (ds01)

On shared GPU servers where Ollama must be launched through Slurm to get GPU
access, use the job scripts in [`benchmark/slurm/`](slurm/).

One-time setup on the cluster:

```bash
git clone <repo-url> ~/SOCC/inTrust && cd ~/SOCC/inTrust
git checkout experiments
# With conda (default on ds01):
conda create --name venv python=3.12 && conda activate venv
# ...or with a classic virtualenv:  python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r benchmark/requirements.txt
mkdir -p ~/logs/slurm
# The Trivy scenarios need the Linux Trivy binary at <repo>/bin/trivy
# (outside Docker it is not installed automatically).  Record the version —
# it is part of the methodology:
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sh -s -- -b ./bin
./bin/trivy --version
# Edit the two .job files: set the --output path and REPO_DIR to your home.
# run_campaign.job activates the conda env named "venv" by default; set the
# CONDA_ENV variable (or CONDA_ENV="" + VENV=/path) if yours differs.
```

**Campaign workflow (recommended)** — one self-contained job that starts
Ollama on the GPU node, pulls the models, runs the experiment, and shuts
down again (survives SSH disconnects):

```bash
sbatch benchmark/slurm/run_campaign.job                                  # scaling_study
sbatch --export=ALL,EXPERIMENT=family_comparison \
       benchmark/slurm/run_campaign.job                                  # experiment 1
sbatch --export=ALL,EXTRA_ARGS="--runs 3 --warmup 1" \
       benchmark/slurm/run_campaign.job                                  # quick test
```

The job pulls the models of the **selected experiment** automatically
(derived from the config, so the pull list can never diverge from what the
benchmark requests).  Override with `MODELS="tag1 tag2"` or point at an
alternative config with `CONFIG=path/to/config.toml` via `--export`.

Monitor with `sq` and `tail -f ~/logs/slurm/benchmark_<jobid>.out`.
Results land in `results/` inside the repo exactly as in a local run.

**Interactive workflow** — a long-lived GPU Ollama server to experiment
against from a login-node shell:

```bash
sbatch benchmark/slurm/ollama_serve.job
# wait until the log shows: inference compute ... name="NVIDIA A30"
INTRUST_OLLAMA_API_BASE=http://127.0.0.1:33111 \
    python -m benchmark.run_benchmark --experiment scaling_study --runs 1 --warmup 0
```

`INTRUST_OLLAMA_API_BASE` overrides the config's `ollama_api_base`, so the
per-job port never requires editing a config file.

**Using a newer Ollama than the system one.**  Some benchmark models need
a newer Ollama than the cluster provides (e.g. stock `deepseek-r1` tool
support, or newer model families).  Ollama is a self-contained binary, so
you can install a current release in your home directory — no root needed:

```bash
curl -L -o /tmp/ollama.tar.zst https://ollama.com/download/ollama-linux-amd64.tar.zst
mkdir -p ~/ollama && tar -xf /tmp/ollama.tar.zst -C ~/ollama
~/ollama/bin/ollama --version
```

(`tar -xf` auto-detects the zstd compression; when upgrading an existing
install, remove the old libraries first: `rm -rf ~/ollama/lib/ollama`.)

Then point the job scripts at it via the `OLLAMA_BIN` variable:

```bash
sbatch --export=ALL,OLLAMA_BIN=$HOME/ollama/bin/ollama,EXPERIMENT=family_comparison \
       benchmark/slurm/run_campaign.job
```

Models are stored in `~/.ollama` regardless of which binary pulled them;
the campaign job's auto-pull refreshes registry manifests, which matters
when a model's tool-capable template only exists in newer manifests
(deepseek-r1).  Each job logs the Ollama binary and version it used, so
the provenance is recorded with the campaign.

Cluster notes:

- The A30's 24 GB fits every configured model (largest: qwen3.5:27b Q4 ≈ 17 GB).
- The job scripts set `OLLAMA_NUM_PARALLEL=4` — without it Ollama serialises
  concurrent requests and the throughput experiment's concurrency levels all
  measure the same serial behaviour.  Each parallel slot multiplies KV-cache
  memory; keep it modest.
- Maximum job runtime is 24 h.  If a full experiment does not fit, submit it
  per experiment (`EXPERIMENT=...`) or reduce `measured_runs` via a config copy.
- GPU sanity check: the Ollama log must contain
  `inference compute ... name="NVIDIA A30"`; a few tokens/second means the
  job is running CPU-only.

---

## 4. Collected metrics (and why)

| Metric | How | Why it matters for the paper |
|---|---|---|
| End-to-end latency (min/max/mean/median/stdev/p95) | `perf_counter` around the full request → response cycle | the primary user-visible cost of each architecture |
| Skill-selection latency | timestamp of the first routing decision (tool call in B, `transfer_to_agent` in A) | isolates the routing overhead the architecture adds |
| LLM time / tool time / formatting time | ADK event timestamps + a timing wrapper around each assessment tool | separates architecture overhead (LLM calls) from constant tool cost |
| CPU avg/peak, RSS avg/peak | `psutil` sampler at 100 ms | resource cost comparison; multi-agent does more LLM round-trips |
| Prompt/completion/total tokens | `event.usage_metadata` (recorded as `N/A` when unavailable — never fails the run) | token economy differs: 1 shared context vs. several smaller ones |
| Routing accuracy | selected skill/agent vs. expected per scenario | do smaller models route worse in one architecture? |
| Throughput (req/s, failures) | waves of N concurrent runs via `asyncio.gather` | behaviour under load per architecture |

Warm-up runs are excluded from every statistic.  Each run uses a **fresh
agent and a fresh ADK session** — no conversation history is ever reused.

---

## 5. Reproducing published results

1. Same machine class, OS, and software versions (`pip freeze`, Ollama
   version, and the exact model tags matter — model tags like `qwen3:8b`
   are mutable upstream, so record `ollama list` output with your results).
2. `python -m benchmark.run_benchmark` with the committed
   `config.default.toml` (seed 42, 5 warm-ups, 30 measured runs).
3. Compare your `results/<experiment>/summary.md` against the published one.

Because LLM token sampling happens inside the Ollama server, individual runs
are not bit-reproducible; the reported statistics (30 runs per cell) are the
reproducible quantity.

## 6. Regenerating figures and tables

Both readers work from the stored raw CSVs — no benchmark re-run needed:

```bash
python -m benchmark.plots        --experiment family_comparison
python -m benchmark.latex_tables --experiment family_comparison

# A specific (older) execution instead of the latest:
python -m benchmark.plots --experiment scaling_study --run-id <run_id>
```

To diagnose failed runs in a campaign, print a per-cell error breakdown
(distinct error messages with counts, plus whether routing had succeeded
before the failure):

```bash
python -m benchmark.errors --experiment family_comparison [--run-id <run_id>]
```

Add `--final-text` to also print one example final response per failing
cell — i.e. what the model said instead of completing the assessment
(useful for classifying protocol failures of borderline models).

The `.tex` files are self-contained booktabs tables ready for `\input{}`
(the paper preamble needs `\usepackage{booktabs}`).

## 7. Troubleshooting

- **Runs time out / Ollama seems stuck.**  When a benchmark run is cancelled
  client-side, the Ollama server may keep draining the in-flight generation;
  subsequent requests queue behind it (Ollama serves one request at a time
  by default).  Restart Ollama to clear the queue.
- **Every run of a thinking model times out.**  Check that
  `think = false` is present under `[provider.model_kwargs]` in the config
  you are passing.
- **`litellm.Timeout` errors in results.**  The model is slower than
  `request_timeout_sec` on your hardware — use smaller models (pilot
  config) or a GPU machine.
- **Multi-agent runs fail with `Tool '<name>_agent' not found`.**  The
  model called the specialist's name as a function instead of using ADK's
  `transfer_to_agent` delegation.  Small models (≲ 2B) do this frequently.
  It is recorded as a failed run with `routing_correct = false` and the
  exact error in the raw JSON — i.e. it is DATA (the multi-agent
  architecture demands more protocol-following capability from the
  orchestrator model), not a framework bug.
- **Thinking enabled, but every run fails with `selected: null` / "no
  assessment tool was executed".**  The completion-token cap is too small:
  a thinking model spends its budget on hidden reasoning and is cut off
  before emitting the tool call (symptom: completion tokens ≈
  `num_predict` exactly).  Raise `num_predict` (e.g. `-1` for unlimited or
  `8192`) and `num_ctx` (e.g. `32768` — thinking turns accumulate across
  the conversation) when running thinking-enabled campaigns.
- **Runs are slow even on a GPU machine.**  Verify Ollama is actually
  using the GPU: `ollama ps` must show `size_vram > 0` (ideally
  "100% GPU") and the ollama process should appear in `nvidia-smi`.
  A few tokens/second means CPU inference.  Also make sure
  `request_timeout_sec` exceeds the realistic duration of one LLM call,
  otherwise litellm kills generations mid-flight.
- **`think = false` has no effect for a specific model tag.**  Ollama
  model tags are mutable and some point at "thinking-only" builds where
  reasoning cannot be disabled.  At the time of writing, `qwen3:4b` maps
  to the Qwen3-2507 *thinking* build (recognisable by its 262k context in
  `ollama show`), unlike `qwen3:0.6b/1.7b/8b/14b` which are classic hybrid
  builds that honour `think = false`.  Verify each tag with a quick
  one-off completion before a campaign, and record `ollama list` digests
  with your results.

### Observed failure modes

Every failure mode seen so far, in decreasing order of severity — use
`python -m benchmark.errors --experiment X --final-text` to classify new
anomalies against this list:

1. **Tool-incapable rejection** — the Ollama server refuses the request
   ("does not support tools") in well under a second.  The model cannot
   participate in either architecture (seen: gemma3, phi4 → excluded).
2. **Stack incompatibility** — the failure sits in the serving stack, not
   the model.  Variants seen: (a) the model tool-calls correctly through
   Ollama's *native* API but not through the litellm `ollama_chat`
   translation — symptom: leaked chat-template tokens such as
   `<|im_start|>` in the final text (granite3.3:8b); (b) a community
   tool-calling template emits a CORRECT call as an unparsed JSON text
   block that never becomes a native tool call
   (MFDoom/deepseek-r1-tool-calling); (c) an outdated server/manifest
   rejects a model that supports tools upstream (stock deepseek-r1 on
   Ollama 0.12 → fixed by a user-local newer Ollama, see the Slurm
   section).  Not model results — exclude or fix the stack, and verify
   with a direct `curl` to `/api/chat` with a `tools` payload.
3. **Format non-adherence** — the model understands the task but emits the
   call as text instead of a native function call, e.g. a
   `transfer_to_agent(...)` pseudo-code block (seen: mistral:7b,
   multi-agent) or a JSON blob naming the correct target agent
   (seen: deepseek-r1:8b, multi-agent).  Genuine capability data.
4. **Hallucinated / fabricated completion** — the model claims the
   assessment happened or will happen, or even invents a complete
   assessment report with made-up findings, without any tool having run
   (seen: mistral:7b single-agent announcing results; command-r7b in both
   architectures announcing the assessment in coherent prose after
   correctly reading the tool descriptions and target; deepseek-r1:8b
   single-agent announcing the dispatch with structured reasoning — and
   extracting the wrong target, the component name instead of the path;
   granite3.3 multi-agent fabricating a full TM Forum report).  Genuine
   data — and the most dangerous mode for a trustworthiness platform.
5. **Clarification instead of action** — the model understands the task
   but asks the user a confirming question ("could you verify the path?")
   instead of acting (seen: orieg/gemma3-tools multi-agent root — while
   the SAME model completes the single-agent flow at 100%, a strong
   cross-architecture contrast).  Genuine data.
6. **Full protocol adherence** — 100% routing and completion in both
   architectures (seen: qwen3:8b, llama3.1:8b, hermes3:8b at
   temperature 0).

## 8. Extending the framework

- **New skill/assessment**: add the skill to the production `skills/`
  directory as usual (plus its `docs/skills/*.md`), then add a scenario
  entry in `benchmark/scenarios.py` and a frozen intent JSON under
  `benchmark/data/intents/`.  Both architectures pick it up automatically.
- **New model**: add its `ollama_chat/<tag>` string to a model list in the
  config — nothing else.
- **New LLM provider**: add a branch in `benchmark/model_factory.py`.
- **New metric**: extend `RunResult` in `benchmark/metrics.py` and fill it
  in `benchmark/runner.py`; add a column to `_CSV_COLUMNS` in
  `benchmark/report_writer.py`.
