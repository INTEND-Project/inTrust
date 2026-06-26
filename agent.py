"""
ADK entry point for InTrust.

This file is discovered automatically by the ADK CLI when you run:

    adk web    — launches the browser-based chat interface
    adk run    — runs the agent interactively in the terminal

The ADK CLI looks for a ``root_agent`` variable in this file.
We simply re-export the agent defined in ``orchestrator/agent.py``.

The web interface lets you interact with InTrust via a chatbot — type a
natural-language request such as:

    "Scan the Python code in ./tools for security issues"
    "Check the Docker image python:3.11-slim for vulnerabilities"
    "Is my filesystem at /opt/project secure?"

and the agent will select the appropriate assessment skill and run it.

Note: the FastAPI HTTP API (started with ``uvicorn main:app``) is a separate
interface for programmatic use.  Both interfaces use the same underlying agent
and skills.
"""

import sys
from pathlib import Path

# When ADK loads this file as part of the 'inTrust' Python package (which
# happens when 'adk web' is run from the parent directory), the project root
# may not be on sys.path, making 'orchestrator', 'skills', etc. unimportable.
# Adding it here ensures all internal modules are always findable regardless
# of how ADK loads this file.
_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# The ADK CLI requires a module-level variable named exactly ``root_agent``.
from orchestrator.agent import root_agent  # noqa: F401, E402
