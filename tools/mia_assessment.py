# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Membership Inference Attack (MIA) tool wrapper.

This module provides the low-level interface for running a membership
inference privacy assessment against the MIA service.  It is called by the
``mia-privacy`` skill.

The assessment is delegated to a remote MIA server: the intent is
initiated via the ``/initiate`` endpoint and the result is polled from the
``/retrieve`` endpoint.  The service returns model privacy metrics that
indicate how resilient a model is to membership inference attacks.

plugin_version: 0.0.9
"""

import json
import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv

# MIA service endpoints are configured in .env (MIA_INITIATE_URL / MIA_RETRIEVE_URL).
# There is deliberately no fallback address: a missing setting is reported as
# an error when the endpoint is used, rather than silently hitting a default.
load_dotenv()
INITIATE_URL = os.getenv("MIA_INITIATE_URL")
RETRIEVE_URL = os.getenv("MIA_RETRIEVE_URL")


def _require_url(url: str | None, env_var: str) -> str:
    if not url:
        raise RuntimeError(f"{env_var} is not set; configure it in .env")
    return url

# MIA version embedded in result records for traceability, mirroring
# TRIVY_VERSION in tools/trivy_scan.py.
#
# Pinned here rather than detected, and that difference matters to a reader.
# Bandit and Trivy are local binaries, so services/executor.py can ask them
# (``trivy --version``); the MIA service is a remote service that exposes no version
# endpoint and returns only the sweep table, so there is nothing to ask.  This
# constant is therefore a statement about which MIA deployment this checkout is
# configured against — it is not evidence from the service, and it goes stale
# silently if the MIA service is upgraded without editing this line.
#
# It is carried into reports as ``method.toolVersion`` beside
# ``method.toolVersionSource: "pinned"``, so a report never presents a
# configured value as a reported one.  Before this existed the field was left
# empty and the report-composing LLM filled the gap with an invented version.
MIA_SERVICE_VERSION = "0.0.9"


# Initiate the assessment on the MIA server.
def initiate_assessment(intent_id: Any, model: Any, data: Any) -> Any:
    timeout = None  # Wait indefinitely for a response.

    payload = json.dumps({"intentid": intent_id, "model": model, "data": data})

    response = httpx.post(
        _require_url(INITIATE_URL, "MIA_INITIATE_URL"),
        data=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )

    return response.json()


# Retrieve the assessment result from the MIA server.
def retrieve_assessment_result(intent_id: Any) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                _require_url(RETRIEVE_URL, "MIA_RETRIEVE_URL"),
                params={"intentid": intent_id, "info": "output"},
            )
            response.raise_for_status()

            # Handle JSON or plain text response.
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return {
                    "status": "success",
                    "version": MIA_SERVICE_VERSION,
                    "data": response.json(),
                }
            return {
                "status": "success",
                "version": MIA_SERVICE_VERSION,
                "data": response.text,
            }

    except httpx.TimeoutException:
        return {"status": "error", "message": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"HTTP error {e.response.status_code}"}
    except Exception as e:  # noqa: BLE001 - surface any transport error as a result
        return {"status": "error", "message": str(e)}


def run_mia_assessment(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Run a membership inference assessment via the MIA service.

    Parameters
    ----------
    intent_request : dict
        TM Forum Intent.  The model reference is read from
        ``parameters.model`` and the shadow data from
        ``parameters.shadowData``.
    logger : JobLogger, optional
        If provided, progress is logged through it.

    Returns
    -------
    dict
        On success: the raw result retrieved from the MIA service.
        On failure: ``{"status": "FAILED", "error": "<message>"}``.
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        model = params.get("model")
        shadow_data = params.get("shadowData")

        if logger:
            logger.info(
                "tool.mia",
                f"Running MIA assessment for intent: {intent_id}\n"
                f"Model: {model}\n"
                f"Shadow data: {shadow_data}",
            )

        # Initiate the assessment on the MIA service, sending the intent id, the model
        # reference and the shadow data.
        #
        # NOTE: initiation is currently disabled.  Running the attack on the MIA service
        # takes a long time, which is not suitable for a demo, so this tool only
        # retrieves the result of an assessment that was already run for this
        # intent id.  For full functionality, enable the three lines below so
        # that each request starts a fresh assessment before retrieving it.
        #initiate = initiate_assessment(intent_id, model, shadow_data)
        #if logger:
        #    logger.info("tool.mia", f"MIA initiation: {initiate}")

        # Retrieve the result for this intent from the MIA service.
        retrieved_result = retrieve_assessment_result(intent_id)

        if logger:
            logger.info(
                "tool.mia",
                f"Retrieved results from the MIA service: {retrieved_result}",
            )

        # Send the raw MIA result back to the orchestrator.  The
        # formal-report-generation skill shapes it into a TM Forum report.
        return retrieved_result

    except Exception as exc:  # noqa: BLE001 - report failures as a result dict
        if logger:
            logger.error("tool.mia", f"MIA assessment error: {exc}")
        return {
            "status": "FAILED",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Quick manual test — run this file directly to test without the HTTP server:
#   python tools/mia_assessment.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_request = {
        "intentId": "intent-demo-789",
        "parameters": {
            "model": {"path": "/data/model_v2.pt"},
            "shadowData": {"type": "synthetic"},
        },
    }

    report = run_mia_assessment(test_request)
    print(json.dumps(report, indent=2))
