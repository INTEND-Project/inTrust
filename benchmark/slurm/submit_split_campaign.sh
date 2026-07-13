#!/bin/bash
# ============================================================================
# Submit a long campaign as TWO chained Slurm jobs (run sequentially on the
# shared GPU, never in parallel) and print the merge command for afterwards.
#
# Why: the scaling study exceeds the 24 h Slurm cap, and a job killed at the
# cap writes NO results (outputs are produced only at the end).  Splitting
# the models across two jobs keeps each part well under 24 h; the second job
# waits for the first via `--dependency=afterany` (it starts even if the
# first hit its time limit), and the two result sets are merged afterwards
# with benchmark/merge_runs.py.
#
# Run this from a LOGIN-NODE shell (it is a submitter, not a Slurm job):
#   benchmark/slurm/submit_split_campaign.sh
#
# Override the split or experiment via environment variables:
#   OLLAMA_BIN=$HOME/ollama/bin/ollama \
#   EXPERIMENT=scaling_study \
#   PART1="ollama_chat/qwen3.5:0.8b ollama_chat/qwen3.5:2b ollama_chat/qwen3.5:4b ollama_chat/qwen3.5:9b" \
#   PART2="ollama_chat/qwen3.5:27b" \
#       benchmark/slurm/submit_split_campaign.sh
# ============================================================================
set -euo pipefail

JOB="$(dirname "$0")/run_campaign.job"
EXPERIMENT="${EXPERIMENT:-scaling_study}"
# Default split: the four smaller qwen3.5 sizes, then the heavy 27b alone.
PART1="${PART1:-ollama_chat/qwen3.5:0.8b ollama_chat/qwen3.5:2b ollama_chat/qwen3.5:4b ollama_chat/qwen3.5:9b}"
PART2="${PART2:-ollama_chat/qwen3.5:27b}"
# Passed through to the jobs (unset by default -> job uses the system ollama).
OLLAMA_BIN="${OLLAMA_BIN:-}"
# Optional docker-image tarball cache, forwarded to both jobs (see README).
INTRUST_IMAGE_CACHE_DIR="${INTRUST_IMAGE_CACHE_DIR:-}"

# Build "--model A --model B ..." (for run_benchmark) and "A-tag B-tag ..."
# (Ollama pull tags = the litellm string minus the ollama_chat/ prefix) for
# one part.  Echoes: "<EXTRA_ARGS>|<MODELS>".
build_part() {
    local extra="" models=""
    for m in $1; do
        extra="${extra} --model ${m}"
        models="${models} ${m#ollama_chat/}"
    done
    echo "${extra# }|${models# }"
}

submit_part() {
    # $1 = model list, $2 = optional --dependency=... argument
    local part; part="$(build_part "$1")"
    local extra_args="${part%%|*}"
    local models="${part##*|}"
    local exports="ALL,EXPERIMENT=${EXPERIMENT},MODELS=${models},EXTRA_ARGS=${extra_args}"
    if [ -n "${OLLAMA_BIN}" ]; then
        exports="${exports},OLLAMA_BIN=${OLLAMA_BIN}"
    fi
    if [ -n "${INTRUST_IMAGE_CACHE_DIR}" ]; then
        exports="${exports},INTRUST_IMAGE_CACHE_DIR=${INTRUST_IMAGE_CACHE_DIR}"
    fi
    sbatch --parsable ${2:+--dependency=$2} --export="${exports}" "${JOB}"
}

echo "Experiment: ${EXPERIMENT}"
echo "Part 1 models: ${PART1}"
echo "Part 2 models: ${PART2}"
echo ""

JID1="$(submit_part "${PART1}" "")"
echo "Submitted part 1: job ${JID1}"
JID2="$(submit_part "${PART2}" "afterany:${JID1}")"
echo "Submitted part 2: job ${JID2}  (starts after ${JID1} finishes)"

echo ""
echo "When BOTH jobs have finished, find their run IDs:"
echo "    ls -t results/${EXPERIMENT}/raw/*.json | head"
echo "and merge them into one result set:"
echo "    python -m benchmark.merge_runs --experiment ${EXPERIMENT} \\"
echo "        --run-ids <part1_run_id> <part2_run_id>"
