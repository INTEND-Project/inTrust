# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Shows a skills-based InTrust agent. Run this with "adk run" or "adk web".

from google.adk.agents import LlmAgent
from google.adk.tools import LongRunningFunctionTool
from .skill_runtime import (
    SKILLS_DIR,
    create_assessment_skill,
    execute_assessment_skill,
    inspect_assessment_skill,
    list_assessment_skills,
)
from .util import load_instruction_from_file

try:
    from google.adk.skills import load_skill_from_dir
    from google.adk.tools import skill_toolset

    ADK_SKILLS_AVAILABLE = True
except ImportError:
    ADK_SKILLS_AVAILABLE = False

APP_NAME="intrust_agent"
USER_ID="rd"
SESSION_ID="1234"

execute_assessment_skill_tool = LongRunningFunctionTool(func=execute_assessment_skill)


SKILLS_BASED_INSTRUCTION = f"""
{load_instruction_from_file("agent_descriptions/intrust_orchestrator.txt")}

Skills-based operating model:

- You are now a single high-level InTrust agent. Do not delegate work to
  downstream agents.
- Treat each directory under `skills/` as an assessment skill. Use skill
  metadata and SKILL.md instructions to decide what capability matches a user
  request or TM Forum intent.
- For assessment requests, call `list_assessment_skills` if you need the skill
  catalog, then call `inspect_assessment_skill` when detailed instructions are
  useful.
- Call `execute_assessment_skill` with the selected `skill_id` and the original
  TM Forum intent payload.
- If no existing skill matches, call `create_assessment_skill` to draft a new
  skill skeleton. Make clear that a skeleton skill still needs an executable
  implementation before it can run real assessments.
- Always return a structured TM Forum aligned report or error response in JSON.
"""

if ADK_SKILLS_AVAILABLE:
    assessment_skills = [
        load_skill_from_dir(skill_path)
        for skill_path in sorted(SKILLS_DIR.iterdir() if SKILLS_DIR.exists() else [])
        if skill_path.is_dir() and (skill_path / "SKILL.md").exists()
    ]
    root_tools = [
        skill_toolset.SkillToolset(skills=assessment_skills),
        execute_assessment_skill_tool,
        create_assessment_skill,
    ]
else:
    root_tools = [
        list_assessment_skills,
        inspect_assessment_skill,
        execute_assessment_skill_tool,
        create_assessment_skill,
    ]


# --- Root skills-based agent ---
root_agent = LlmAgent(
    name="InTrustSkillAgent",
    model="gemini-2.5-flash-lite",
    instruction=SKILLS_BASED_INSTRUCTION,
    description=(
        "A skills-based trustworthiness assessment agent that selects, "
        "inspects, executes, and drafts assessment skills for InTrust."
    ),
    tools=root_tools,
)
