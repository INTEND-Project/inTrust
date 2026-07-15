# Benchmark summary — family_comparison

- Run ID: `family_comparison_20260713-200551_9eb5afe3`
- Generated: 2026-07-13T22:28:54.237353
- Warm-up runs (excluded): 5
- Measured runs per cell: 30
- Seed: 42
- Scenarios: bandit_static_code, trivy_filesystem, trivy_docker_image, unsupported_request

## Latency and routing per cell (concurrency = 1)

Isolated behaviour: this table uses **concurrency = 1** runs only, so latency reflects the architecture itself, not queueing (the throughput section covers behaviour under load).  Routing accuracy is independent of run success — a run can route correctly and still fail during execution (tool error, timeout).  For the `unsupported_request` (gatekeeping) scenario "correct" means the model refused (selected no skill); for the others it means the expected skill was selected.  Gatekeeping is only interpretable for models that demonstrate tool-calling ability (native-call adherence ≥ 20% on supported scenarios); a model that cannot emit native calls trivially "refuses" everything, so its gatekeeping is shown as `n/a (cannot act)`.

| Architecture | Model | Scenario | n | Mean (ms) | Median | Stdev | p95 | Min | Max | Routing acc. | Failures |
|---|---|---|---|---|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 30 | 7438 | 7655 | 1240 | 9245 | 5888 | 9279 | n/a (cannot act) | 0 |
| multi_agent | ollama_chat/llama3.1:8b | bandit_static_code | 30 | 5079 | 4998 | 526 | 6186 | 4443 | 6243 | 100% | 0 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 30 | 4874 | 4919 | 512 | 5575 | 4051 | 5683 | 100% | 0 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 30 | 6960 | 6923 | 623 | 7915 | 5796 | 7944 | 100% | 0 |
| multi_agent | ollama_chat/llama3.1:8b | unsupported_request | 30 | 5913 | 4883 | 3000 | 16772 | 4621 | 16805 | 0% | 0 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 30 | 11817 | 11653 | 1365 | 14244 | 9479 | 14270 | 80% | 6 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 30 | 14714 | 14539 | 987 | 16902 | 13349 | 16591 | 40% | 18 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 30 | 2201 | 2159 | 374 | 2714 | 1588 | 2722 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 14274 | 13310 | 3094 | 20294 | 10646 | 20405 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 14442 | 14333 | 1997 | 17790 | 11226 | 18171 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 14396 | 14026 | 1274 | 17462 | 12500 | 18214 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 5310 | 4307 | 2079 | 9561 | 3787 | 9814 | 80% | 0 |
| single_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 0% | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 30 | 9178 | 8336 | 1821 | 12406 | 7271 | 12486 | n/a (cannot act) | 0 |
| single_agent | ollama_chat/llama3.1:8b | bandit_static_code | 30 | 5156 | 4744 | 869 | 7127 | 4456 | 7101 | 60% | 12 |
| single_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 30 | 4436 | 4152 | 621 | 5641 | 3693 | 5597 | 40% | 18 |
| single_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 30 | 6005 | 6006 | 171 | 6324 | 5616 | 6321 | 60% | 12 |
| single_agent | ollama_chat/llama3.1:8b | unsupported_request | 30 | 3336 | 3060 | 632 | 4388 | 2498 | 4402 | 100% | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 30 | 6242 | 6401 | 658 | 7214 | 4831 | 7442 | 100% | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 30 | 7070 | 7079 | 514 | 8006 | 6399 | 8012 | 100% | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 30 | 8006 | 7621 | 1175 | 10887 | 6162 | 10974 | 100% | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 30 | 3881 | 4482 | 893 | 4735 | 2424 | 4791 | 60% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 8844 | 8684 | 909 | 10349 | 6863 | 10553 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 9216 | 9020 | 640 | 10622 | 8075 | 10823 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 11231 | 11210 | 840 | 12854 | 9849 | 12947 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 6057 | 6068 | 344 | 6616 | 5369 | 6658 | 100% | 0 |

## Routing decomposition (concurrency = 1)

Separates the routing **decision** from **protocol adherence**.  *Decision* = the model identified the correct capability (in a native call **or** described in text); *Native-call* = it expressed that via the native function-calling protocol (not prose); *Routing* = both (the strict metric above).  For `unsupported_request`, *Decision* is genuine gatekeeping (the model declined to route anywhere) — reported only for tool-calling-capable models (native-call ≥ 20% on supported scenarios), else `n/a (cannot act)`.  Native-call adherence is exact; the text-derived decision is a documented heuristic (see routing_analysis.py).

| Architecture | Model | Scenario | n | Decision acc. | Native-call | Routing acc. |
|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 30 | 100% | 0% | 0% |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 30 | 80% | 0% | 0% |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 30 | 100% | 0% | 0% |
| multi_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 30 | n/a (cannot act) | 0% | 100% |
| multi_agent | ollama_chat/llama3.1:8b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/llama3.1:8b | unsupported_request | 30 | 0% | 100% | 0% |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 30 | 100% | 0% | 0% |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 30 | 100% | 80% | 80% |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 30 | 80% | 40% | 40% |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 30 | 100% | 0% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 80% | 20% | 80% |
| single_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 30 | 100% | 0% | 0% |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 30 | 100% | 0% | 0% |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 30 | 100% | 0% | 0% |
| single_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 30 | n/a (cannot act) | 0% | 100% |
| single_agent | ollama_chat/llama3.1:8b | bandit_static_code | 30 | 100% | 60% | 60% |
| single_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 30 | 100% | 40% | 40% |
| single_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 30 | 100% | 60% | 60% |
| single_agent | ollama_chat/llama3.1:8b | unsupported_request | 30 | 40% | 0% | 100% |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 30 | 60% | 40% | 60% |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 100% | 0% | 100% |

## Resource usage per cell

Harness = benchmark client process (orchestration overhead); Server = Ollama process tree (inference); GPU via nvidia-smi.

| Architecture | Model | Scenario | Harness CPU avg (%) | Harness RSS peak (MB) | Server CPU avg (%) | Server RSS peak (MB) | GPU util avg (%) | VRAM peak (MB) | Tokens (mean total) |
|---|---|---|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 5.5 | 319 | 104.5 | 3504 | 57.7 | 9759 | 1694 |
| multi_agent | ollama_chat/llama3.1:8b | bandit_static_code | 6.0 | 323 | 102.4 | 2426 | 32.9 | 9019 | 3468 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 6.2 | 324 | 103.7 | 4802 | 36.4 | 9019 | 3310 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 5.7 | 323 | 79.7 | 3631 | 30.1 | 9019 | 3468 |
| multi_agent | ollama_chat/llama3.1:8b | unsupported_request | 6.0 | 317 | 99.9 | 5973 | 32.6 | 9019 | 3277 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 5.7 | 322 | 101.0 | 10873 | 50.6 | 11335 | 4273 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 5.4 | 318 | 91.4 | 9682 | 47.4 | 11335 | 4521 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 6.4 | 317 | 106.4 | 10114 | 41.1 | 11335 | 1757 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5.5 | 317 | 103.5 | 1777 | 42.7 | 6913 | 4722 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5.5 | 323 | 103.2 | 2079 | 43.2 | 6913 | 4550 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5.4 | 317 | 92.3 | 1927 | 37.8 | 6913 | 4604 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5.9 | 323 | 106.1 | 2063 | 43.6 | 6913 | 2145 |
| single_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 5.4 | 319 | 104.4 | 3527 | 55.8 | 9751 | 852 |
| single_agent | ollama_chat/llama3.1:8b | bandit_static_code | 6.0 | 323 | 101.4 | 1200 | 43.4 | 9017 | 2530 |
| single_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 6.0 | 323 | 103.2 | 1188 | 43.5 | 9019 | 2454 |
| single_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 6.1 | 323 | 74.0 | 1184 | 29.3 | 9019 | 2503 |
| single_agent | ollama_chat/llama3.1:8b | unsupported_request | 6.3 | 323 | 106.3 | 969 | 49.5 | 9019 | 1870 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 5.7 | 317 | 100.2 | 1657 | 49.1 | 11335 | 3789 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 5.9 | 318 | 99.9 | 1672 | 48.9 | 11335 | 3766 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 5.7 | 319 | 80.9 | 1664 | 39.2 | 11335 | 3820 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 5.9 | 318 | 104.7 | 1672 | 46.5 | 11335 | 2509 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5.7 | 295 | 102.8 | 1285 | 44.9 | 6913 | 4269 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5.7 | 316 | 102.6 | 1302 | 42.9 | 6913 | 4233 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5.4 | 298 | 88.1 | 1295 | 37.4 | 6913 | 4312 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5.8 | 316 | 105.1 | 1301 | 46.0 | 6913 | 2121 |

## Throughput

| Architecture | Model | Scenario | Concurrency | Req/s | Avg latency (ms) | Failures |
|---|---|---|---|---|---|---|
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 1 | 0.113 | 8844 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 1 | 0.089 | 11231 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 1 | 0.109 | 9216 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 1 | 0.165 | 6057 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 1 | 0.070 | 14274 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 1 | 0.069 | 14396 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 1 | 0.069 | 14442 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 1 | 0.188 | 5310 | 0 |
| single_agent | ollama_chat/llama3.1:8b | bandit_static_code | 1 | 0.143 | 5156 | 12 |
| single_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 1 | 0.131 | 6005 | 12 |
| single_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 1 | 0.138 | 4436 | 18 |
| single_agent | ollama_chat/llama3.1:8b | unsupported_request | 1 | 0.300 | 3336 | 0 |
| multi_agent | ollama_chat/llama3.1:8b | bandit_static_code | 1 | 0.197 | 5079 | 0 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_filesystem | 1 | 0.144 | 6960 | 0 |
| multi_agent | ollama_chat/llama3.1:8b | trivy_docker_image | 1 | 0.205 | 4874 | 0 |
| multi_agent | ollama_chat/llama3.1:8b | unsupported_request | 1 | 0.169 | 5913 | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 1 | 0.160 | 6242 | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 1 | 0.125 | 8006 | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 1 | 0.141 | 7070 | 0 |
| single_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 1 | 0.258 | 3881 | 0 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | bandit_static_code | 1 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_filesystem | 1 | 0.051 | 14714 | 18 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | trivy_docker_image | 1 | 0.080 | 11817 | 6 |
| multi_agent | ollama_chat/orieg/gemma3-tools:12b-ft-v2 | unsupported_request | 1 | 0.454 | 2201 | 0 |
| single_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 1 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 1 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 1 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 1 | 0.109 | 9178 | 0 |
| multi_agent | ollama_chat/deepseek-r1:8b | bandit_static_code | 1 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_filesystem | 1 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | trivy_docker_image | 1 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/deepseek-r1:8b | unsupported_request | 1 | 0.134 | 7438 | 0 |

---
Regenerate figures:  `python -m benchmark.plots --experiment family_comparison`
Regenerate tables:   `python -m benchmark.latex_tables --experiment family_comparison`
