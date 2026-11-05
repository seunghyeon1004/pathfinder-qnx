#!/bin/sh
# pf-capture.sh <out.kev> <seconds> -- <command> [args...]
# Runs on the QNX target AS ROOT. Starts tracelogger in wide mode (priorities in every thread event),
# runs the command, stops tracing.   Example:  sudo ./pf-capture.sh mars_none.kev 4 -- ./mars none 3
OUT=$1; SECS=$2; shift 2; [ "$1" = "--" ] && shift
[ "$(id -u)" = 0 ] || { echo "pf-capture: must run as root (tracelogger requirement)"; exit 1; }
rm -f "$OUT"
tracelogger -w -b 256 -k 16 -s "$SECS" -f "$OUT" >/dev/null 2>&1 &
TL=$!
sleep 1
"$@"
RC=$?
wait $TL
echo "pf-capture: $OUT $(ls -l "$OUT" | awk '{print $5}') bytes, command exit=$RC"
exit 0
