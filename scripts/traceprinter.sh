#!/bin/bash
# traceprinter.sh <in.kev> <out.txt>   -> text dump used by the analyzer.
# Uses the SDP's `traceprinter` if it is on PATH (after `source qnxsdp-env.sh`), else the Docker env (see docs/RUN.md).
set -e
IN=$(cd "$(dirname "$1")" && pwd)/$(basename "$1"); OUT=$2
if command -v traceprinter >/dev/null 2>&1; then
  traceprinter -n -f "$IN" > "$OUT"
else
  docker run --rm -v "${PF_QNX_VOLUME:-qnx-home}":/home/qnx -v "$(dirname "$IN")":/kev:ro "${PF_QNX_IMAGE:-qnx-env:base}" \
    bash -c 'source ~/qnx800/qnxsdp-env.sh >/dev/null && traceprinter -n -f /kev/"$0"' "$(basename "$IN")" 2>/dev/null > "$OUT"
fi
