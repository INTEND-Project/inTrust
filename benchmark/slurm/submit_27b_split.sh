#!/bin/bash
# ============================================================================
# Submit the heavy 27B leg of the scaling study as TWO chained Slurm jobs,
# split BY SCENARIO PAIR (not by model), and print the 3-way merge command.
#
# Why: even alone, the 27B model does not finish the four scenarios x two
# architectures within the 24 h Slurm cap, and a job killed at the cap writes
# NO results (outputs are produced only at the end).  The small-model leg
# (0.8B-9B) already completed as "part 1"; this script re-runs ONLY the 27B
# model, splitting its four scenarios across two jobs so each stays well under
# the cap.  The second job waits for the first via `--dependency=afterany`
# (it starts even if the first hit its time limit), and all three result sets
# are merged afterwards with benchmark/merge_runs.py.
#
# Each job runs BOTH architectures over its scenario pair; the two pairs
# partition the four scenarios, so the merged 27B cells never overlap (nor do
# they overlap the small-model part, which has no 27B rows).
#
# Run this from a LOGIN-NODE shell (it is a submitter, not a Slurm job):
#   benchmark/slurm/submit_27b_split.sh
#
# Override the model, scenario split, or experiment via environment variables:
#   OLLAMA_BIN=$HOME/ollama/bin/ollama \
#   INTRUST_IMAGE_CACHE_DIR=$HOME/intrust_images \
#   MODEL=ollama_chat/qwen3.5:27b \
#   PART1_SCENARIOS="bandit_static_code trivy_docker_image" \
#   PART2_SCENARIOS="trivy_filesystem unsupported_request" \
#       benchmark/slurm/submit_27b_split.sh
# ============================================================================
set -euo pipefail

JOB="$(dirname "$0")/run_campaign.job"
EXPERIMENT="${EXPERIMENT:-scaling_study}"
# The single heavy model this split re-runs.
MODEL="${MODEL:-ollama_chat/qwen3.5:27b}"
# Default scenario split: the two Trivy-heavy scans that need the most work
# (static-code + docker-image) first, then the lighter filesystem scan plus
# the fast gatekeeping refusals.  Each half is two of the four scenarios.
PART1_SCENARIOS="${PART1_SCENARIOS:-bandit_static_code trivy_docker_image}"
PART2_SCENARIOS="${PART2_SCENARIOS:-trivy_filesystem unsupported_request}"
# Passed through to the jobs (unset by default -> job uses the system ollama).
OLLAMA_BIN="${OLLAMA_BIN:-}"
# Optional docker-image tarball cache, forwarded to both jobs (see README).
INTRUST_IMAGE_CACHE_DIR="${INTRUST_IMAGE_CACHE_DIR:-}"

# Ollama pull tag = the litellm model string minus the ollama_chat/ prefix.
MODEL_TAG="${MODEL#ollama_chat/}"

submit_part() {
    # $1 = space-separated scenario keys, $2 = optional --dependency=... arg.
    # Build "--model M --scenario s1 --scenario s2 ..." for run_benchmark.
    local extra_args="--model ${MODEL}"
    local s
    for s in $1; do
        extra_args="${extra_args} --scenario ${s}"
    done
    local exports="ALL,EXPERIMENT=${EXPERIMENT},MODELS=${MODEL_TAG},EXTRA_ARGS=${extra_args}"
    if [ -n "${OLLAMA_BIN}" ]; then
        exports="${exports},OLLAMA_BIN=${OLLAMA_BIN}"
    fi
    if [ -n "${INTRUST_IMAGE_CACHE_DIR}" ]; then
        exports="${exports},INTRUST_IMAGE_CACHE_DIR=${INTRUST_IMAGE_CACHE_DIR}"
    fi
    sbatch --parsable ${2:+--dependency=$2} --export="${exports}" "${JOB}"
}

echo "Experiment:      ${EXPERIMENT}"
echo "Model:           ${MODEL}"
echo "Part 1 scenarios: ${PART1_SCENARIOS}"
echo "Part 2 scenarios: ${PART2_SCENARIOS}"
echo ""

JID1="$(submit_part "${PART1_SCENARIOS}" "")"
echo "Submitted 27B part 1: job ${JID1}"
JID2="$(submit_part "${PART2_SCENARIOS}" "afterany:${JID1}")"
echo "Submitted 27B part 2: job ${JID2}  (starts after ${JID1} finishes)"

echo ""
echo "When BOTH jobs have finished, find their run IDs:"
echo "    ls -t results/${EXPERIMENT}/raw/*.json | head"
echo "and merge them WITH the existing small-model part into one result set:"
echo "    python -m benchmark.merge_runs --experiment ${EXPERIMENT} \\"
echo "        --run-ids <small_models_run_id> <27b_part1_run_id> <27b_part2_run_id>"
echo ""
echo "The three parts partition the model x architecture x scenario grid"
echo "(small models: all scenarios; 27B: split across the two pairs above),"
echo "so merge_runs concatenates them with no overlapping cells."
