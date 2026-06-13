#!/usr/bin/env bash
# Build (and optionally push) the two autocodabench base images.
#
# Usage:
#   docker/build_and_push.sh [NAMESPACE] [TAG] [--push]
#
#   NAMESPACE   registry/org the images are tagged under
#               (default: $AUTOCODABENCH_DOCKER_NAMESPACE or "autocodabench")
#   TAG         image tag (default: "latest")
#   --push      also push both images to the registry (requires `docker login`)
#
# Produces:
#   <NAMESPACE>/autocodabench-base-cpu:<TAG>   (from codalab/codalab-legacy:py312)
#   <NAMESPACE>/autocodabench-base-gpu:<TAG>   (from codalab/codalab-legacy:gpu310)
#
# These are the images autocodabench uses as the default docker_image for new
# bundles (CPU unless the plan needs a GPU). Point the runner at your namespace
# with AUTOCODABENCH_DOCKER_IMAGE / AUTOCODABENCH_DOCKER_IMAGE_GPU, or edit the
# defaults in src/autocodabench/runner/execution.py. See docker/README.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAMESPACE="${1:-${AUTOCODABENCH_DOCKER_NAMESPACE:-autocodabench}}"
TAG="${2:-latest}"
PUSH=0
for arg in "$@"; do
  [ "$arg" = "--push" ] && PUSH=1
done

CPU_IMAGE="${NAMESPACE}/autocodabench-base-cpu:${TAG}"
GPU_IMAGE="${NAMESPACE}/autocodabench-base-gpu:${TAG}"

echo "Building ${CPU_IMAGE}"
docker build -f "${HERE}/autocodabench-cpu.Dockerfile" -t "${CPU_IMAGE}" "${HERE}"

echo "Building ${GPU_IMAGE}"
docker build -f "${HERE}/autocodabench-gpu.Dockerfile" -t "${GPU_IMAGE}" "${HERE}"

if [ "${PUSH}" -eq 1 ]; then
  echo "Pushing ${CPU_IMAGE}"
  docker push "${CPU_IMAGE}"
  echo "Pushing ${GPU_IMAGE}"
  docker push "${GPU_IMAGE}"
else
  echo
  echo "Built locally (not pushed). To publish:"
  echo "  docker login"
  echo "  docker/build_and_push.sh ${NAMESPACE} ${TAG} --push"
fi

echo
echo "To make these the runner defaults, export:"
echo "  AUTOCODABENCH_DOCKER_IMAGE=${CPU_IMAGE}"
echo "  AUTOCODABENCH_DOCKER_IMAGE_GPU=${GPU_IMAGE}"
