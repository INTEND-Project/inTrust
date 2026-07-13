#!/bin/bash
# ============================================================================
# One-time prep: cache the docker-image scenario's images LOCALLY so the
# benchmark never pulls from a registry during a campaign.
#
# Trivy pulls each image from the registry on EVERY scan, and a full campaign
# (~1000+ scans across 5 images) blows Docker Hub's anonymous/authenticated
# pull limits.  This script pulls each image ONCE (<=5 pulls total) into an
# OCI tarball with `crane` (a static, daemon-less binary), and the docker
# tool then scans `trivy image --input <tar>` when INTRUST_IMAGE_CACHE_DIR
# is set (see tools/trivy_scan.py::_cached_image_tar).
#
# Run once from the repo root on the cluster:
#   export INTRUST_IMAGE_CACHE_DIR=$HOME/SOCC/inTrust/benchmark/data/image_cache
#   bash benchmark/slurm/prepare_docker_images.sh
# Then pass INTRUST_IMAGE_CACHE_DIR to the campaign jobs (see README).
# ============================================================================
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
CACHE_DIR="${INTRUST_IMAGE_CACHE_DIR:-${REPO_DIR}/benchmark/data/image_cache}"
INTENTS_DIR="${REPO_DIR}/benchmark/data/intents"
CRANE="${CRANE:-}"

mkdir -p "${CACHE_DIR}"

# ---- locate or install crane (static Go binary, no root, no daemon) --------
if [ -z "${CRANE}" ]; then
    if command -v crane >/dev/null 2>&1; then
        CRANE="$(command -v crane)"
    elif [ -x "${REPO_DIR}/bin/crane" ]; then
        CRANE="${REPO_DIR}/bin/crane"
    else
        echo "crane not found — installing a local copy into ${REPO_DIR}/bin ..."
        ver="v0.20.2"
        url="https://github.com/google/go-containerregistry/releases/download/${ver}/go-containerregistry_Linux_x86_64.tar.gz"
        mkdir -p "${REPO_DIR}/bin"
        curl -sSL "${url}" | tar -xz -C "${REPO_DIR}/bin" crane
        CRANE="${REPO_DIR}/bin/crane"
    fi
fi
echo "Using crane: ${CRANE} ($("${CRANE}" version 2>/dev/null || echo unknown))"
echo "Cache dir:   ${CACHE_DIR}"
echo ""

# ---- read the image references from the docker-image intents ----------------
# Each intent_trivy_image_v*.json has parameters.dockerImage = "<image:tag>".
images="$(python3 - "$INTENTS_DIR" <<'PYEOF'
import glob, json, os, sys
intents_dir = sys.argv[1]
seen = []
for path in sorted(glob.glob(os.path.join(intents_dir, "intent_trivy_image_*.json"))):
    with open(path, encoding="utf-8") as fh:
        img = json.load(fh).get("parameters", {}).get("dockerImage")
    if img and img not in seen:
        seen.append(img)
print(" ".join(seen))
PYEOF
)"

if [ -z "${images}" ]; then
    echo "ERROR: no dockerImage values found in ${INTENTS_DIR}" >&2
    exit 1
fi

# ---- pull each image once into a tarball ------------------------------------
for image in ${images}; do
    safe="$(echo "${image}" | sed 's#[/:]#_#g')"
    out="${CACHE_DIR}/${safe}.tar"
    if [ -s "${out}" ]; then
        echo "already cached: ${image} -> ${out}"
        continue
    fi
    echo "pulling ${image} -> ${out}"
    "${CRANE}" pull "${image}" "${out}"
done

echo ""
echo "Done.  Point campaigns at the cache with:"
echo "    export INTRUST_IMAGE_CACHE_DIR=${CACHE_DIR}"
