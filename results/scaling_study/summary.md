# Benchmark summary — scaling_study

- Run ID: `scaling_study_merged_20260722-134305_11c9f8a3`
- Generated: 2026-07-22T13:43:08.967996
- Warm-up runs (excluded): 5
- Measured runs per cell: 30
- Seed: 42
- Scenarios: bandit_static_code, trivy_filesystem, trivy_docker_image, unsupported_request

## Latency and routing per cell (concurrency = 1)

Isolated behaviour: this table uses **concurrency = 1** runs only, so latency reflects the architecture itself, not queueing (the throughput section covers behaviour under load).  Routing accuracy is independent of run success — a run can route correctly and still fail during execution (tool error, timeout).  For the `unsupported_request` (gatekeeping) scenario "correct" means the model refused (selected no skill); for the others it means the expected skill was selected.  Gatekeeping is only interpretable for models that demonstrate tool-calling ability (native-call adherence ≥ 20% on supported scenarios); a model that cannot emit native calls trivially "refuses" everything, so its gatekeeping is shown as `n/a (cannot act)`.

| Architecture | Model | Scenario | n | Mean (ms) | Median | Stdev | p95 | Min | Max | Routing acc. | Failures |
|---|---|---|---|---|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 30 | 8410 | 8364 | 966 | 10371 | 7001 | 10212 | 100% | 18 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 30 | 147311 | 147311 | 8295 | 163148 | 141445 | 153176 | 100% | 28 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 30 | 102754 | 140675 | 98069 | 334739 | 17771 | 477176 | 100% | 1 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 30 | 5854 | 2932 | 6434 | 19320 | 1628 | 19528 | 80% | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 30 | 550742 | 562846 | 63528 | 606072 | 335331 | 606773 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 30 | 433005 | 432856 | 3306 | 438003 | 419927 | 438238 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 30 | 355627 | 456241 | 183753 | 459813 | 26414 | 460991 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 30 | 9880 | 10705 | 2175 | 12114 | 6324 | 12165 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 30 | 10556 | 10730 | 2382 | 15768 | 6510 | 16405 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 30 | 18651 | 21527 | 7279 | 29489 | 7754 | 32377 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 30 | 11552 | 11136 | 2818 | 16790 | 7463 | 17038 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 30 | 4842 | 5497 | 1113 | 6134 | 2882 | 6150 | 0% | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 30 | 10300 | 9984 | 1281 | 12730 | 8056 | 13098 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 30 | 14866 | 12896 | 5114 | 24107 | 10299 | 23028 | 100% | 21 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 30 | 11576 | 11299 | 1679 | 15911 | 10063 | 19603 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 30 | 3157 | 2476 | 1427 | 6017 | 1823 | 6091 | 80% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 14495 | 13725 | 3160 | 21133 | 10443 | 21413 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 15661 | 15078 | 3087 | 23186 | 10965 | 28216 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 14716 | 14481 | 1606 | 18702 | 12342 | 18721 | 100% | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 5117 | 4413 | 2067 | 9671 | 3076 | 9680 | 80% | 0 |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 30 | 16834 | 15487 | 4108 | 26958 | 12878 | 26148 | 100% | 18 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 30 | N/A | N/A | N/A | N/A | N/A | N/A | 100% | 30 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 30 | 32878 | 19293 | 30978 | 105706 | 14114 | 105876 | 100% | 6 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 30 | 3014 | 3323 | 1044 | 4808 | 1660 | 4854 | 40% | 0 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 30 | 17258 | 15282 | 3411 | 22402 | 13652 | 22422 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 30 | 13840 | 13665 | 649 | 15432 | 13021 | 15881 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 30 | 16511 | 16353 | 792 | 17835 | 15109 | 17843 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 30 | 10062 | 9801 | 1171 | 11731 | 8091 | 11739 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 30 | 11005 | 11093 | 1354 | 13669 | 8315 | 14668 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 30 | 25718 | 24997 | 5701 | 36826 | 8794 | 37113 | 100% | 2 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 30 | 15678 | 14941 | 1892 | 20277 | 13476 | 21201 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 30 | 4692 | 4748 | 626 | 5951 | 3571 | 6111 | 0% | 0 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 30 | 9940 | 9966 | 1627 | 13156 | 7279 | 13159 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 30 | 12139 | 12257 | 3128 | 16598 | 7344 | 16509 | 100% | 19 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 30 | 11104 | 11435 | 2342 | 14635 | 7296 | 14931 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 30 | 4794 | 4914 | 582 | 5475 | 3409 | 5512 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 9000 | 8877 | 961 | 10907 | 6980 | 10949 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 12987 | 10572 | 5449 | 24752 | 8310 | 24372 | 100% | 14 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 11238 | 11507 | 1194 | 12979 | 8579 | 13081 | 100% | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 6061 | 6153 | 634 | 6950 | 4400 | 6952 | 100% | 0 |

## Routing decomposition (concurrency = 1)

Separates the routing **decision** from **protocol adherence**.  *Decision* = the model identified the correct capability (in a native call **or** described in text); *Native-call* = it expressed that via the native function-calling protocol (not prose); *Routing* = both (the strict metric above).  For `unsupported_request`, *Decision* is genuine gatekeeping (the model declined to route anywhere) — reported only for tool-calling-capable models (native-call ≥ 20% on supported scenarios), else `n/a (cannot act)`.  Native-call adherence is exact; the text-derived decision is a documented heuristic (see routing_analysis.py).

| Architecture | Model | Scenario | n | Decision acc. | Native-call | Routing acc. |
|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 30 | 40% | 20% | 80% |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 30 | 100% | 0% | 100% |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 30 | 0% | 100% | 0% |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 30 | 80% | 20% | 80% |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 100% | 100% | 100% |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 80% | 20% | 80% |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 30 | 40% | 60% | 40% |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 30 | 100% | 0% | 100% |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 30 | 0% | 100% | 0% |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 30 | 100% | 0% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 30 | 100% | 100% | 100% |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 30 | 100% | 0% | 100% |

## Resource usage per cell

Harness = benchmark client process (orchestration overhead); Server = Ollama process tree (inference); GPU via nvidia-smi.

| Architecture | Model | Scenario | Harness CPU avg (%) | Harness RSS peak (MB) | Server CPU avg (%) | Server RSS peak (MB) | GPU util avg (%) | VRAM peak (MB) | Tokens (mean total) |
|---|---|---|---|---|---|---|---|---|---|
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 6.6 | 333 | 105.9 | 4480 | 17.3 | 1663 | 6127 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 5.9 | 352 | 64.5 | 9270 | 15.8 | 1663 | 212211 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 5.8 | 351 | 63.2 | 9329 | 12.7 | 1663 | 154899 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 6.5 | 355 | 111.5 | 9190 | 21.4 | 1663 | 4920 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 5.3 | 361 | 99.8 | 10536 | 80.5 | 17541 | 238945 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 5.4 | 376 | 99.2 | 10115 | 81.1 | 17541 | 191489 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 5.3 | 344 | 89.4 | 10530 | 69.0 | 17541 | 112984 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 5.2 | 345 | 103.1 | 9323 | 70.8 | 17541 | 1912 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 6.0 | 367 | 104.8 | 1394 | 25.4 | 3435 | 5849 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 5.7 | 371 | 63.9 | 2053 | 17.4 | 3435 | 5445 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 5.7 | 367 | 84.1 | 1573 | 21.4 | 3435 | 5284 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 6.1 | 361 | 110.0 | 2992 | 23.9 | 3435 | 3038 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 5.7 | 361 | 104.7 | 1735 | 35.6 | 4287 | 4616 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 5.8 | 377 | 76.4 | 2057 | 24.5 | 4287 | 4444 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 5.7 | 361 | 89.6 | 1887 | 28.3 | 4287 | 4535 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 5.9 | 363 | 109.8 | 2022 | 32.7 | 4287 | 2073 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5.5 | 367 | 103.7 | 1805 | 42.7 | 6913 | 4752 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5.5 | 381 | 94.3 | 3529 | 40.0 | 6913 | 4544 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5.4 | 367 | 92.6 | 3100 | 39.9 | 6913 | 4616 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5.5 | 371 | 106.8 | 6514 | 46.1 | 6913 | 2145 |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 7.4 | 307 | 102.1 | 922 | 17.2 | 1663 | 24718 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 7.3 | 318 | 93.8 | 2243 | 15.4 | 1663 | 63500 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 6.7 | 328 | 112.7 | 4195 | 22.1 | 1663 | 3188 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 5.3 | 313 | 101.1 | 1544 | 68.5 | 17539 | 4256 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 5.5 | 337 | 101.5 | 1576 | 67.6 | 17539 | 4144 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 5.3 | 309 | 91.6 | 1538 | 62.0 | 17539 | 4222 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 5.3 | 312 | 103.0 | 1571 | 70.5 | 17539 | 2069 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 6.3 | 355 | 102.4 | 1228 | 24.6 | 3433 | 9048 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 5.6 | 367 | 42.3 | 1237 | 11.7 | 3433 | 8967 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 5.8 | 355 | 69.4 | 1232 | 16.2 | 3433 | 9610 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 6.4 | 367 | 109.4 | 1235 | 27.3 | 3435 | 4079 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 5.9 | 361 | 101.9 | 1273 | 37.2 | 4287 | 6999 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 5.9 | 371 | 82.7 | 1269 | 28.0 | 4287 | 6438 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 5.6 | 361 | 77.9 | 1270 | 28.6 | 4287 | 5987 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 5.5 | 361 | 106.5 | 1273 | 41.1 | 4287 | 2097 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5.6 | 363 | 102.9 | 1317 | 46.1 | 6913 | 4273 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5.7 | 375 | 78.5 | 1388 | 36.0 | 6913 | 4230 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5.5 | 363 | 88.2 | 1327 | 37.8 | 6913 | 4305 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5.4 | 367 | 105.3 | 1328 | 47.5 | 6913 | 2121 |

## Throughput

| Architecture | Model | Scenario | Concurrency | Req/s | Avg latency (ms) | Failures |
|---|---|---|---|---|---|---|
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 1 | 0.041 | 16834 | 18 |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 5 | 0.078 | 26591 | 16 |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 10 | 0.062 | 52493 | 15 |
| single_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 20 | 0.105 | 68545 | 15 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 1 | 0.028 | 32878 | 6 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 5 | 0.043 | 48168 | 9 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 10 | 0.059 | 79875 | 7 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 20 | 0.050 | 136774 | 8 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 1 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 5 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 10 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 20 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 1 | 0.332 | 3014 | 0 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 5 | 0.532 | 6581 | 0 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 10 | 0.514 | 12036 | 0 |
| single_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 20 | 0.501 | 20614 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 1 | 0.016 | 8410 | 18 |
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 5 | 0.036 | 17228 | 16 |
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 10 | 0.048 | 31336 | 17 |
| multi_agent | ollama_chat/qwen3.5:0.8b | bandit_static_code | 20 | 0.040 | 54365 | 18 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 1 | 0.006 | 102754 | 1 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 5 | 0.016 | 158266 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 10 | 0.011 | 372260 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_filesystem | 20 | 0.009 | 674619 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 1 | 0.002 | 147311 | 28 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 5 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 10 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:0.8b | trivy_docker_image | 20 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 1 | 0.171 | 5854 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 5 | 0.191 | 10149 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 10 | 0.281 | 15770 | 0 |
| multi_agent | ollama_chat/qwen3.5:0.8b | unsupported_request | 20 | 0.304 | 23548 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 1 | 0.091 | 11005 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 5 | 0.152 | 25916 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 10 | 0.153 | 50230 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 20 | 0.148 | 85785 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 1 | 0.064 | 15678 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 5 | 0.117 | 36098 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 10 | 0.122 | 65897 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 20 | 0.121 | 108161 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 1 | 0.038 | 25718 | 2 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 5 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 10 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 20 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 1 | 0.213 | 4692 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 5 | 0.319 | 11422 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 10 | 0.334 | 19877 | 0 |
| single_agent | ollama_chat/qwen3.5:2b | unsupported_request | 20 | 0.324 | 32791 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 1 | 0.095 | 10556 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 5 | 0.144 | 24962 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 10 | 0.150 | 45962 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | bandit_static_code | 20 | 0.147 | 76872 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 1 | 0.087 | 11552 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 5 | 0.145 | 26251 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 10 | 0.157 | 44418 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_filesystem | 20 | 0.154 | 72072 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 1 | 0.054 | 18651 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 5 | 0.070 | 48409 | 3 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 10 | 0.021 | 120997 | 20 |
| multi_agent | ollama_chat/qwen3.5:2b | trivy_docker_image | 20 | 0.085 | 151184 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 1 | 0.207 | 4842 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 5 | 0.309 | 11332 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 10 | 0.311 | 21688 | 0 |
| multi_agent | ollama_chat/qwen3.5:2b | unsupported_request | 20 | 0.319 | 32449 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 1 | 0.101 | 9940 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 5 | 0.133 | 27926 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 10 | 0.144 | 50674 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 20 | 0.143 | 79641 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 1 | 0.090 | 11104 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 5 | 0.147 | 24942 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 10 | 0.161 | 43357 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 20 | 0.162 | 71578 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 1 | 0.032 | 12139 | 19 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 5 | 0.007 | 53892 | 28 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 10 | 0.086 | 96558 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 20 | 0.080 | 85253 | 13 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 1 | 0.209 | 4794 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 5 | 0.233 | 13156 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 10 | 0.239 | 23377 | 0 |
| single_agent | ollama_chat/qwen3.5:4b | unsupported_request | 20 | 0.239 | 38139 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 1 | 0.097 | 10300 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 5 | 0.129 | 28541 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 10 | 0.138 | 51317 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | bandit_static_code | 20 | 0.135 | 85600 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 1 | 0.086 | 11576 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 5 | 0.142 | 25248 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 10 | 0.147 | 47840 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_filesystem | 20 | 0.146 | 76414 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 1 | 0.020 | 14866 | 21 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 5 | 0.115 | 34229 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 10 | 0.135 | 52119 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | trivy_docker_image | 20 | 0.105 | 115846 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 1 | 0.317 | 3157 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 5 | 0.407 | 7037 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 10 | 0.432 | 12047 | 0 |
| multi_agent | ollama_chat/qwen3.5:4b | unsupported_request | 20 | 0.433 | 18938 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 1 | 0.111 | 9000 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5 | 0.136 | 26372 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 10 | 0.134 | 49076 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 20 | 0.135 | 78999 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 1 | 0.089 | 11238 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5 | 0.128 | 26606 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 10 | 0.130 | 49352 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 20 | 0.130 | 78784 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 1 | 0.039 | 12987 | 14 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5 | 0.116 | 30524 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 10 | 0.136 | 46914 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 20 | 0.097 | 86116 | 6 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 1 | 0.165 | 6061 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5 | 0.180 | 16887 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 10 | 0.180 | 31219 | 0 |
| single_agent | ollama_chat/qwen3.5:9b | unsupported_request | 20 | 0.184 | 48919 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 1 | 0.069 | 14495 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 5 | 0.079 | 43853 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 10 | 0.078 | 85807 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | bandit_static_code | 20 | 0.080 | 134363 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 1 | 0.068 | 14716 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 5 | 0.096 | 36704 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 10 | 0.100 | 67008 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_filesystem | 20 | 0.098 | 109785 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 1 | 0.064 | 15661 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 5 | 0.069 | 53713 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 10 | 0.086 | 75276 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | trivy_docker_image | 20 | 0.009 | 119868 | 25 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 1 | 0.195 | 5117 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 5 | 0.215 | 13147 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 10 | 0.222 | 23151 | 0 |
| multi_agent | ollama_chat/qwen3.5:9b | unsupported_request | 20 | 0.222 | 36991 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 1 | 0.058 | 17258 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 5 | 0.064 | 55277 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 10 | 0.064 | 102931 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 20 | 0.065 | 170122 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 1 | 0.072 | 13840 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 5 | 0.083 | 42879 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 10 | 0.083 | 81450 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 20 | 0.084 | 132288 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 1 | 0.002 | 550742 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 5 | 0.000 | 71173 | 29 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 10 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:27b | bandit_static_code | 20 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 1 | 0.002 | 433005 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 5 | 0.000 | 0 | 30 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 10 | 0.000 | 155109 | 28 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_docker_image | 20 | 0.000 | 0 | 30 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 1 | 0.061 | 16511 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 5 | 0.077 | 47191 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 10 | 0.078 | 87506 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 20 | 0.077 | 144384 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 1 | 0.099 | 10062 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 5 | 0.106 | 29008 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 10 | 0.107 | 52149 | 0 |
| single_agent | ollama_chat/qwen3.5:27b | unsupported_request | 20 | 0.107 | 83820 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 1 | 0.003 | 355627 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 5 | 0.002 | 957193 | 17 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 10 | 0.001 | 111543 | 26 |
| multi_agent | ollama_chat/qwen3.5:27b | trivy_filesystem | 20 | 0.002 | 176609 | 25 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 1 | 0.101 | 9880 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 5 | 0.108 | 27475 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 10 | 0.109 | 50314 | 0 |
| multi_agent | ollama_chat/qwen3.5:27b | unsupported_request | 20 | 0.109 | 81009 | 0 |

---
Regenerate figures:  `python -m benchmark.plots --experiment scaling_study`
Regenerate tables:   `python -m benchmark.latex_tables --experiment scaling_study`
