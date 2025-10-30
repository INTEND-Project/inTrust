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

# Shows how to call all the sub-agents using the LLM's reasoning ability. Run this with "adk run" or "adk web"

from google.adk.agents import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import LongRunningFunctionTool
from .tools.mia_assessment import run_mia_assessment
from .tools.bandit_assessment import run_bandit_assessment
from .tools.trivy_scan import *
#from typing import Dict, Any

from .util import load_instruction_from_file

APP_NAME="intrust_agent"
USER_ID="rd"
SESSION_ID="1234"

mia_assessment_tool = LongRunningFunctionTool(func=run_mia_assessment)
bandit_assessment_tool = LongRunningFunctionTool(func=run_bandit_assessment)
image_scan_tool = LongRunningFunctionTool(func=scan_docker_image)
fs_scan_tool = LongRunningFunctionTool(func=scan_fs)
k8s_scan_tool = LongRunningFunctionTool(func=scan_k8_cluster)


# --- Sub Agent 1: MIA Assessment ---
mia_assessment_agent = LlmAgent(
    name="MiaAssessmentAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/mia_assessment_agent.txt"),
    description="Evaluates the privacy resilience of machine learning models against membership inference attacks, which attempt to infer whether a specific data sample was used during model training.",
    output_key="mia_assessment",  # Save result to state
    tools=[mia_assessment_tool]
)

# --- Sub Agent 2: Robustness Assessment ---
robustness_assessment_agent = LlmAgent(
    name="RobustnessAssessmentAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/robustness_assessment_agent.txt"),
    description="Assesses how resistant a trained machine learning model is to input perturbations, adversarial noise, or operational anomalies. It determines whether small variations in sensor data or other features significantly affect model predictions.",
    output_key="robustness_assessment", # Save result to state
)

# --- Sub Agent 3: Fairness Assessment ---
fairness_assessment_agent = LlmAgent(
    name="FairnessAssessmentAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/fairness_assessment_agent.txt"),
    description="Analyzes whether a machine learning model exhibits bias toward specific groups or input categories.",
    output_key="fairness_assessment",  # Save result to state
)

# --- Sub Agent 4: Static Code Vulnerability Assessment Using Bandit ---
bandit_assessment_agent = LlmAgent(
    name="BanditAssessmentAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/bandit_assessment_agent.txt"),
    description="Evaluates Python source code for potential security vulnerabilities using Bandit, a static analysis tool that inspects code for common software weaknesses and insecure coding patterns.",
    output_key="bandit_assessment",  # Save result to state
    tools=[bandit_assessment_tool]
)

# --- Sub Agent 5: Docker Image Security Scan using Trivy ---
image_scan_agent = LlmAgent(
    name="ImageScanAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/trivy_image_scanner_agent.txt"),
    description="Evaluate the security posture of containerized applications by scanning Docker images for known vulnerabilities using Trivy.",
    output_key="image_scan",  # Save result to state
    tools=[image_scan_tool]
)

# --- Sub Agent 6: File System Security Scan using Trivy ---
fs_scan_agent = LlmAgent(
    name="FileSystemScanAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/trivy_fs_scanner_agent.txt"),
    description="Assess a local directory or filesystem for vulnerabilities, secrets, and misconfigurations using Trivy.",
    output_key="fs_scan",  # Save result to state
    tools=[fs_scan_tool]
)

# --- Sub Agent 7: File System Security Scan using Trivy ---
k8s_scan_agent = LlmAgent(
    name="KubernetesClusterScanAgent",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/trivy_k8s_scanner_agent.txt"),
    description="Evaluates the security configuration and compliance posture of a Kubernetes cluster using Trivy.",
    output_key="k8s_scan",  # Save result to state
    tools=[k8s_scan_tool]
)

# --- Main orchestrator agent ---
intrust_orchestrator_agent = LlmAgent(
    name="IntrustOrchestrator",
    model="gemini-2.0-flash-lite",
    instruction=load_instruction_from_file("agent_descriptions/intrust_orchestrator.txt"),
    description="The InTrust Orchestrator Agent manages trustworthiness assessments across distributed computing environments by coordinating specialized downstream agents. It acts as the central reasoning and delegation component of the InTrust system, powered by an LLM.",
    tools=[
        AgentTool(mia_assessment_agent),
        AgentTool(robustness_assessment_agent),
        AgentTool(fairness_assessment_agent),
        AgentTool(bandit_assessment_agent),
        AgentTool(image_scan_agent),
        AgentTool(fs_scan_agent),
        AgentTool(k8s_scan_agent)
    ],
)

# --- Root Agent for the Runner ---
# The runner will now execute the workflow
root_agent = intrust_orchestrator_agent
