#!/bin/bash
# Build target programs on a machine without a native SDP (e.g. Apple Silicon): runs `make` inside an
# amd64 container that has QNX SDP 8.0 installed in a docker volume (see docs/RUN.md).
# usage: scripts/docker-make.sh [make args]
set -e
R=$(cd "$(dirname "$0")/.." && pwd)
docker run --rm -v "${PF_QNX_VOLUME:-qnx-home}":/home/qnx -v "$R":/pf "${PF_QNX_IMAGE:-qnx-env:base}" \
  bash -c 'source ~/qnx800/qnxsdp-env.sh >/dev/null && cd /pf/target && make "$@"' _ "$@" 2>&1 | grep -v "requested image's platform"
