"""
Model factory — turns a model string from the config file into an ADK model.

This is the single place where LLM providers are wired up.  To add a new
provider later (e.g. OpenAI or a remote vLLM server), add a branch here;
nothing else in the benchmark needs to change.

Why a factory?  ADK's ``LlmAgent`` accepts either a plain model-name string
(resolved to Gemini) or a ``BaseLlm`` instance.  For locally hosted Ollama
models we must construct a ``LiteLlm`` instance pointed at the local server.
"""

import json
import urllib.request

from google.adk.models.lite_llm import LiteLlm

from .config import BenchmarkConfig


def make_model(model_string: str, cfg: BenchmarkConfig):
    """
    Create an ADK model object for the given model string.

    Parameters
    ----------
    model_string : str
        Model identifier from the config file, e.g. ``"ollama_chat/qwen3:8b"``.
        The ``ollama_chat/`` prefix is the LiteLLM route for Ollama's chat API.
    cfg : BenchmarkConfig
        Provides the provider type and the Ollama server URL.

    Returns
    -------
    LiteLlm or str
        A fresh model object.  IMPORTANT: each call returns a NEW instance so
        that, in the multi-agent architecture, every sub-agent owns its own
        LLM object (a stated property of Architecture A).
    """
    if cfg.provider_type == "ollama":
        # LiteLlm forwards extra kwargs to the litellm completion call:
        # - api_base routes the request to the local Ollama server,
        # - timeout makes a stuck generation fail with a clear error,
        # - cfg.model_kwargs carries generation settings from the config
        #   (think=false, num_predict, num_ctx, ...) — recorded methodology.
        return LiteLlm(
            model=model_string,
            api_base=cfg.ollama_api_base,
            timeout=cfg.request_timeout_sec,
            **cfg.model_kwargs,
        )

    if cfg.provider_type == "gemini":
        # Gemini models are referenced by plain string; ADK resolves them
        # natively (requires GEMINI_API_KEY in the environment).
        return model_string

    raise ValueError(
        f"Unknown provider type '{cfg.provider_type}'. "
        "Add a branch in benchmark/model_factory.py to support it."
    )


def unload_model(model_string: str, cfg: BenchmarkConfig) -> None:
    """
    Ask the Ollama server to evict a model from memory (best-effort).

    Called when the benchmark switches models so that only the model under
    test is resident on the GPU — otherwise ``OLLAMA_KEEP_ALIVE`` keeps
    earlier models loaded and the per-model VRAM/RSS figures are inflated by
    co-residency.  The reload of the next model lands in the excluded
    warm-up runs.  Failures are swallowed (this is a measurement nicety, not
    correctness-critical).
    """
    if cfg.provider_type != "ollama":
        return
    tag = model_string.split("/", 1)[-1]  # "ollama_chat/qwen3:8b" -> "qwen3:8b"
    # keep_alive: 0 tells Ollama to unload the model immediately after this
    # (empty) request.
    payload = json.dumps({"model": tag, "keep_alive": 0}).encode("utf-8")
    url = cfg.ollama_api_base.rstrip("/") + "/api/generate"
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        print(f"    (could not unload {tag}: {type(exc).__name__})")
