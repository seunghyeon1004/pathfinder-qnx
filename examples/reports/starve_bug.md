# Pathfinder report: starve_bug

Trace: `starve_bug.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 26884 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f starve_bug.kev`

## F1 [CRITICAL] Deadline misses: ctrl missed 39 of 98 jobs (period 20 ms, worst release-to-completion 141 ms)

Window: 2477.9 - 2618.9 ms. Evidence events: #14313, #14314.

**Root cause.** Task ctrl has a 20 ms period (from its pf_period markers) but 39 of 98 jobs finished more than one period after their release, worst 141 ms (job 71 started 138 ms late, events #14313, #14314). The misses overlap F2 (CPU starvation), which is the cause.

**Fix.** Fix the upstream cause first (see the linked finding). If the job legitimately needs more time, raise the period or shorten the work.

## F2 [CRITICAL] CPU starvation: ctrl (prio 20) kept off the CPU up to 140 ms by hog (prio 40), 5 times

Window: 1274.5 - 1414.9 ms. Evidence events: #8352.

**Root cause.** ctrl (priority 20) was ready to run but waited up to 140 ms because hog (priority 40) kept the CPU, 5 times. With fixed-priority scheduling this is expected whenever a higher-priority thread is busy; it is a problem only if ctrl has a deadline.

**Fix.** Bound the high-priority thread's CPU burst (sleep/yield or move work to a lower priority), use sporadic scheduling (SCHED_SPORADIC), or adaptive partitioning to guarantee a CPU budget.

Leads to: F1.
