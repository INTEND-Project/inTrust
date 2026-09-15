#!/bin/bash
# ============================================================================
# Submit the registry-size sweep as ONE sequential chain of Slurm jobs.
#
# Experiments live in benchmark/config.registry_sweep.toml.  Phases:
#   family      registry_<size>            Qwen3.5:9B, Llama3.1:8B, Gemma-3:12B
#   scaling     scaling_registry_<size>    Qwen3.5 0.8B, 2B, 4B
#   scaling27b  scaling27b_registry_<size> Qwen3.5 27B, split into two
#               scenario-pair jobs per size (its multi-agent flow loops at
#               ~500 s per request, so one job could approach the 24 h cap)
#
# Every job waits for the previous one (--dependency=afterany), so jobs never
# overlap on the GPU or on the Ollama port, and a job hitting its time limit
# does not stall the rest of the chain.
#
# Run from a LOGIN-NODE shell in the repository root:
#   OLLAMA_BIN=$HOME/ollama/bin/ollama \
#   INTRUST_IMAGE_CACHE_DIR=$HOME/SOCC/inTrust/benchmark/data/image_cache \
#       benchmark/slurm/submit_registry_sweep.sh
#
# Selectors (environment variables):
#   PHASES="family scaling scaling27b"   phases to submit (default: all three)
#   FAMILY_SIZES="04 08 16 32"           registry sizes for the family phase
#   SCALING_SIZES="04 32"                registry sizes for both scaling phases
#
# Completing the scaling grid later (8 and 16 skills):
#   PHASES="scaling scaling27b" SCALING_SIZES="08 16" \
#   OLLAMA_BIN=... INTRUST_IMAGE_CACHE_DIR=... benchmark/slurm/submit_registry_sweep.sh
# ============================================================================
set -euo pipefail

JOB="$(dirname "$0")/run_campaign.job"
CONFIG="${CONFIG:-benchmark/config.registry_sweep.toml}"
PHASES="${PHASES:-family scaling scaling27b}"
FAMILY_SIZES="${FAMILY_SIZES:-04 08 16 32}"
SCALING_SIZES="${SCALING_SIZES:-04 32}"
OLLAMA_BIN="${OLLAMA_BIN:-}"
INTRUST_IMAGE_CACHE_DIR="${INTRUST_IMAGE_CACHE_DIR:-}"

# The container-image scenario must scan from the local cache: pulling from
# Docker Hub hits its anonymous rate limit and corrupts the results.
if [ -z "${INTRUST_IMAGE_CACHE_DIR}" ]; then
    echo "ERROR: INTRUST_IMAGE_CACHE_DIR is not set (see prepare_docker_images.sh)." >&2
    exit 1
fi
if ! ls "${INTRUST_IMAGE_CACHE_DIR}"/*.tar > /dev/null 2>&1; then
    echo "ERROR: no image tarballs in ${INTRUST_IMAGE_CACHE_DIR} (run prepare_docker_images.sh)." >&2
    exit 1
fi

# The two scenario pairs used to split 27B jobs (together: all four scenarios).
PAIR_A="--scenario bandit_static_code --scenario trivy_docker_image"
PAIR_B="--scenario trivy_filesystem --scenario unsupported_request"

# Build the chain as "EXPERIMENT|EXTRA_ARGS" entries.
ENTRIES=()
for phase in ${PHASES}; do
    case "${phase}" in
        family)
            for size in ${FAMILY_SIZES}; do ENTRIES+=("registry_${size}|"); done ;;
        scaling)
            for size in ${SCALING_SIZES}; do ENTRIES+=("scaling_registry_${size}|"); done ;;
        scaling27b)
            for size in ${SCALING_SIZES}; do
                ENTRIES+=("scaling27b_registry_${size}|${PAIR_A}")
                ENTRIES+=("scaling27b_registry_${size}|${PAIR_B}")
            done ;;
        *)
            echo "ERROR: unknown phase '${phase}' (use family, scaling, scaling27b)." >&2
            exit 1 ;;
    esac
done

submit() {
    # $1 = experiment, $2 = extra run_benchmark args, $3 = dependency or ""
    # MODELS=auto: run_campaign.job pulls exactly the models of $1 from CONFIG.
    local exports="ALL,CONFIG=${CONFIG},EXPERIMENT=$1,EXTRA_ARGS=$2,MODELS=auto"
    exports="${exports},OLLAMA_NUM_PARALLEL=1,INTRUST_IMAGE_CACHE_DIR=${INTRUST_IMAGE_CACHE_DIR}"
    if [ -n "${OLLAMA_BIN}" ]; then
        exports="${exports},OLLAMA_BIN=${OLLAMA_BIN}"
    fi
    if [ -n "$3" ]; then
        sbatch --parsable --dependency="$3" --export="${exports}" "${JOB}"
    else
        sbatch --parsable --export="${exports}" "${JOB}"
    fi
}

echo "Config:  ${CONFIG}"
echo "Phases:  ${PHASES}   family sizes: ${FAMILY_SIZES}   scaling sizes: ${SCALING_SIZES}"
echo "Jobs:    ${#ENTRIES[@]} (sequential chain)"
echo ""

prev=""
for entry in "${ENTRIES[@]}"; do
    exp="${entry%%|*}"
    extra="${entry#*|}"
    dep=""
    if [ -n "${prev}" ]; then
        dep="afterany:${prev}"
    fi
    jid="$(submit "${exp}" "${extra}" "${dep}")"
    printf "  job %-10s %-26s %s\n" "${jid}" "${exp}" "${extra:-all scenarios}"
    prev="${jid}"
done

echo ""
echo "When the chain has finished:"
echo "  1. Merge the two scenario-pair parts of each 27B registry size, e.g."
echo "       ls -t results/scaling27b_registry_04/raw/*.json"
echo "       python -m benchmark.merge_runs --config ${CONFIG} \\"
echo "           --experiment scaling27b_registry_04 --run-ids <partA> <partB>"
echo "  2. Confirm scoring is current (expect 0 runs re-scored):"
echo "       python -m benchmark.rescore_runs --config ${CONFIG} \\"
echo "           --experiment <experiment> --run-ids <run_id> --check"
