# Pathfinder report: mars_protect

Trace: `mars_protect.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 28352 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f mars_protect.kev`

## F1 [INFO] CPU starvation: meteo (prio 10) kept off the CPU up to 160 ms by comms (prio 20), 10 times

Window: 3002.2 - 3162.2 ms. Evidence events: #15514.

**Root cause.** meteo (priority 10) was ready to run but waited up to 160 ms because comms (priority 20) kept the CPU, 10 times. With fixed-priority scheduling this is expected whenever a higher-priority thread is busy; it is a problem only if meteo has a deadline.

**Fix.** Bound the high-priority thread's CPU burst (sleep/yield or move work to a lower priority), use sporadic scheduling (SCHED_SPORADIC), or adaptive partitioning to guarantee a CPU budget.
