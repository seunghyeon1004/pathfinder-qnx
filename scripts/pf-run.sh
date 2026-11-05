#!/bin/bash
# pf-run.sh <program> <mode> [seconds] [capture-seconds]
# Pushes target/build/x86_64/<program> to the QNX VM, records a kernel trace around it, pulls examples/<program>_<mode>.kev
# and writes the traceprinter dump next to it. Needs the VM (scripts/qnx-vm.sh start) and a built target (scripts/docker-make.sh).
set -e
D=$(cd "$(dirname "$0")/.." && pwd); V="$D/scripts/qnx-vm.sh"
P=$1; M=$2; S=${3:-}; C=${4:-7}
OUT="${PF_OUT:-$D/examples}"; mkdir -p "$OUT"
"$V" push "$D/target/build/x86_64/$P" "/data/home/qnxuser/$P" </dev/null
"$V" push "$D/target/pf-capture.sh" /data/home/qnxuser/pf-capture.sh </dev/null
# any earlier instance (e.g. a deadlocked one) must be gone, otherwise the binary is "busy"
timeout 60 "$V" sudo "sh -c 'cd /data/home/qnxuser && timeout 60 ./pf-capture.sh ${P}_${M}.kev $C -- ./$P $M $S'" </dev/null || true
timeout 120 "$V" pull "/data/home/qnxuser/${P}_${M}.kev" "$OUT/${P}_${M}.kev" </dev/null
"$D/scripts/traceprinter.sh" "$OUT/${P}_${M}.kev" "$OUT/${P}_${M}.traceprinter.txt"
echo "recorded $OUT/${P}_${M}.kev ($(wc -c < "$OUT/${P}_${M}.kev") bytes)"
