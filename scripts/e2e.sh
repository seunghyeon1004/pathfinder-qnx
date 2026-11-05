#!/bin/bash
# End-to-end acceptance run on a real QNX 8.0 target (QEMU quick-start image):
#   build with qcc -> boot VM -> run each scenario in bug and fix mode under tracelogger -> traceprinter -> Pathfinder
#   -> assert that the expected findings appear (bug) and disappear (fix).  Exit code != 0 on any mismatch.
# Needs: docker env with the SDP (docs/RUN.md) or `source qnxsdp-env.sh` + native make, Homebrew/apt qemu, python3.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
cd "$D"
PY=${PYTHON:-python3}
OUT=${PF_OUT:-$D/examples}
mkdir -p "$OUT/traces" "$OUT/reports"
if command -v qcc >/dev/null 2>&1; then (cd target && make); else scripts/docker-make.sh; fi
scripts/qnx-vm.sh start
# program mode seconds
for run in "mars none 3" "mars sem 3" "mars inherit 3" "mars protect 3" "ipc_deadlock bug" "ipc_deadlock fix" "deadline bug 2" "deadline fix 2" "starve bug 2" "starve fix 2"; do
  set -- $run
  P=$1; M=$2; S=${3:-}
  # the IPC deadlock needs a longer capture window (it lasts 1.2 s plus shutdown)
  C=6; [ "$P" = ipc_deadlock ] && C=8
  PF_OUT="$OUT/traces" scripts/pf-run.sh "$P" "$M" "$S" "$C"
  gzip -9 -c "$OUT/traces/${P}_${M}.traceprinter.txt" > "$OUT/traces/${P}_${M}.txt.gz"
  rm -f "$OUT/traces/${P}_${M}.traceprinter.txt"
done
scripts/qnx-vm.sh stop || true
FAIL=0
check() {  # name  expected-kinds(space separated, "-" = no critical findings)
  local trace="$OUT/traces/$1.txt.gz" want="$2" out
  out=$(cd host && $PY -m pathfinder analyze "$trace" --out "$OUT/reports" --title "$1" 2>&1) || true
  echo "$out" | sed 's/^/    /'
  if [ "$want" = "-" ]; then
    echo "$out" | grep -q '\[critical\]' && { echo "FAIL $1: unexpected critical finding"; FAIL=1; } || echo "PASS $1: clean"
  else
    for k in $want; do
      echo "$out" | grep -qi "$k" || { echo "FAIL $1: missing '$k'"; FAIL=1; }
    done
    [ $FAIL = 0 ] && echo "PASS $1: $want detected"
  fi
  return 0
}
check mars_none "Priority.inversion Deadline.misses Watchdog"
check mars_sem "Priority.inversion.*semaphore Deadline.misses Watchdog"
check mars_inherit "-"
check mars_protect "-"
check ipc_deadlock_bug "IPC.deadlock"
check ipc_deadlock_fix "-"
check deadline_bug "Deadline.misses Long.critical.section"
check deadline_fix "-"
check starve_bug "Deadline.misses CPU.starvation"
check starve_fix "-"
exit $FAIL
