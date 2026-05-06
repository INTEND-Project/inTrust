# 🧠 InTrust: Agentic Trustworthiness Assessment Framework

## 1. Overview

**InTrust** is a modular, AI-powered framework for performing **trustworthiness, security, and privacy assessments** of data pipelines, AI models, and infrastructure components in the **computing continuum**.
It combines a **plugin-based architecture**, **LLM-driven agents**, and **WebAssembly sandboxing** to enable secure, flexible, and cross-organizational evaluations.

Each assessment is triggered by a **TM Forum Intent** — a high-level declarative request — which the **InTrust skill agent** interprets and maps to a file-backed assessment skill.
This architecture enables intent-driven management of trustworthy AI systems.

---

## 2. Key Features

### 🔌 Plugin Architecture

* Enables **extensibility and modularity**: each trustworthiness or security assessment is implemented as an independent plugin.
* Plugins can be written in any programming language and compiled into **WebAssembly (Wasm)** binaries.
* The core engine dynamically loads and executes plugins at runtime, based on incoming TM Forum intents.
* Promotes **interoperability and secure collaboration** between different organizations without sharing source code.

---

### 🧩 Agentic Approach (Powered by Google ADK)

* Implemented as a **skills-based agent system** using the **Google Agent Development Kit (ADK)**.
* A central **InTrust skill agent** receives TM Forum Intents, interprets them, and activates a suitable assessment skill.
* Each skill specializes in a particular aspect of trustworthiness (e.g., privacy, vulnerability scanning, code analysis).
* **LLMs** enable intelligent orchestration, dynamic plugin selection, and reasoning about user intents.
* Supports **long-running function tools** for handling resource-intensive operations asynchronously.

---

### 🧱 Extism for Secure, Sandboxed Execution

* Uses **Extism** to execute plugins safely inside **WebAssembly sandboxes**.
* Allows untrusted third-party code to be executed securely and in isolation.
* Provides **cross-language interoperability**, enabling contributors to add trust assessment tools in Python, Rust, Go, or C++.
* Ensures platform portability and runtime consistency.

---

## 3. Installation Prerequisites

Before running InTrust, ensure your environment is properly set up.

### 🐍 Step 1: Install Python

Install **Python 3.9 or higher** from [python.org](https://www.python.org/downloads/).
Verify installation:

```bash
python --version
```

---

### 🧰 Step 2: Create and Activate a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

---

### 📦 Step 3: Install Dependencies

Install **Google ADK** and other required Python libraries:

```bash
pip install -r requirements.txt
```

---

### 🔑 Step 4: Create a .env File for API Access

In the project root, create a file named .env and add your Google Gemini API credentials.
These environment variables are required for LLM-powered orchestration via the Google ADK.

Example .env:

```bash
GOOGLE_API_KEY=<your_google_api_key_here>
GOOGLE_GENAI_USE_VERTEXAI=FALSE
```

💡 Replace <your_google_api_key_here> with your actual API key from the Google AI Studio.

---

### 🧮 Step 5: Install Bandit

Used by the **static code analysis agent**:

```bash
pip install bandit
```

---

### 🧱 Step 6: Prepare Trivy Binaries

Required for agents performing **Docker image**, **file system**, or **Kubernetes** scans.

1. Download **Trivy** from [https://github.com/aquasecurity/trivy/releases](https://github.com/aquasecurity/trivy/releases).
2. Extract it into the `bin/` folder:

   * On Linux/macOS → `bin/trivy`
   * On Windows → `bin/trivy.exe`

---

### ⚙️ Step 7: Install Extism PDK

Required for compiling and running Wasm-based plugins.
Follow the official instructions here:
👉 [Extism Python PDK](https://github.com/extism/python-pdk)

---

## 4. Project Structure

```
intrust/
│
├── agent_descriptions/ # textual descriptions of agents   
│
├── tools/ # Python code for tools to be used by agents   
│
├── plugins/ # wasm-based plugins
│
├── bin/ Linux and Windows executbales of various third-party tools (e.g. Trivy)
│   
├── intents/ # sample intent definitions to play with inTrust
│
├── requirements.txt
├── README.md
└── agent.py                         # Entry point for starting InTrust system
```

---

## 4.1 Skills-Based Architecture

InTrust now uses one high-level ADK agent instead of an orchestrator that wraps
multiple downstream agents.

When `google-adk>=1.25.0` is installed, the agent loads `skills/` through ADK's
native `SkillToolset`. Older ADK environments fall back to the local
skill-management tools exposed by `skill_runtime.py`.

The root agent has four skill-management tools:

* `list_assessment_skills` - discover available assessment skills.
* `inspect_assessment_skill` - read a skill's metadata and `SKILL.md` instructions.
* `execute_assessment_skill` - execute the selected skill against the original TM Forum Intent.
* `create_assessment_skill` - draft a new file-backed skill skeleton when no existing skill matches.

Each skill lives in:

```text
skills/<skill_id>/
├── SKILL.md
└── metadata.json
```

Executable skills point to an implementation in `tools/` through
`metadata.json` fields such as `tool_module` and `tool_function`. Skills without
an implementation can still be selected, but they return a
`PENDING_IMPLEMENTATION` report.

---

## 5. How to Run the Application

You can run **InTrust** using the **Google ADK CLI** in two main modes: interactive **CLI mode** or **Web UI** mode.

### ▶️ Option 1: Command-Line (Interactive)

Run:

```bash
adk run .
```

You will enter an **interactive chat interface** with the InTrust skill agent.
You can start with simple prompts such as:

```
What is InTrust?
What tools can InTrust use for trustworthiness assessments?
```

Then, to trigger an actual assessment, provide a **TM Forum Intent** in JSON format:

```json
{
  "intentId": "intent-001",
  "name": "Security Assessment",
  "parameters": {
    "codeReference": {
      "path": "./src/app.py"
    },
    "assessmentType": "static_code_analysis"
  }
}
```

---

### 🌐 Option 2: Web Interface

Run:

```bash
adk web ..
```

This will launch a **local web server** with an interactive chatbot interface powered by LLMs.
You can:

* Chat naturally to explore InTrust capabilities, or
* Paste full TM Forum Intents to perform real assessments.

The InTrust skill agent will automatically interpret your intent, select the right assessment skill, and return a structured TM Forum report.

---

## 6. Example Use Cases

* 🧠 **ML Privacy Auditing** → Run MIA assessment on machine learning models before deployment.
* 🧾 **Code Security Review** → Static vulnerability scanning of Python projects using Bandit.
* 🧱 **Infrastructure Hardening** → Scan Docker images, file systems, or Kubernetes clusters using Trivy.

---

## 7. License

This project is released under the **MIT License**.
© 2025 SINTEF Digital, Ericsson AB.

