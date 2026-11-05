# Pathfinder report: mars_none

Trace: `mars_none.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 29358 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f mars_none.kev`

## F1 [CRITICAL] Priority inversion: bus_mgr (prio 30) blocked on a mutex held by meteo (prio 10), starved by comms (prio 20)

Window: 3783.1 - 3934.4 ms. Evidence events: #19895, #19898, #19913, #19918, #19937.

**Root cause.** bus_mgr (priority 30) needed a mutex that meteo (base priority 10) was holding, and had to wait. While it waited, meteo could not run: meteo stayed at priority 10 (it was never raised) and was kept off the CPU by comms, which runs at a priority between the two. That is unbounded priority inversion: the high-priority work was delayed by an unrelated medium-priority thread for up to 151 ms (150 ms of that with meteo ready but not scheduled), 10 times in this trace. Owner identified via kernel SYNC_MUTEX_LOCK owner field. Evidence: events #19895, #19898, #19913, #19918.

**Fix.** This mutex was created with PTHREAD_PRIO_NONE, which turns priority inheritance off. Use PTHREAD_PRIO_INHERIT (the default on QNX; just do not override it) so meteo is raised to priority 30 while bus_mgr waits, or PTHREAD_PRIO_PROTECT with a ceiling of at least 30. Shorten the critical section as a second line of defence.

Leads to: F2.

## F2 [CRITICAL] Deadline misses: bus_mgr missed 10 of 30 jobs (period 100 ms, worst release-to-completion 155 ms)

Window: 3784.2 - 3939.4 ms. Evidence events: #19892, #20142.

**Root cause.** Task bus_mgr has a 100 ms period (from its pf_period markers) but 10 of 30 jobs finished more than one period after their release, worst 155 ms (job 27 started -1 ms late, events #19892, #20142). The misses overlap F1 (Priority inversion), which is the cause.

**Fix.** Fix the upstream cause first (see the linked finding). If the job legitimately needs more time, raise the period or shorten the work.

Leads to: F3.

## F3 [CRITICAL] Watchdog fired 7 time(s): the system would have reset

Window: 1793.7 - 3637.5 ms. Evidence events: #10250, #11016, #11904, #14812, #15527, #16680.

**Root cause.** The application's watchdog reported a missed heartbeat 7 time(s) (events #10250, #11016, #11904, #14812). Preceded by F2.

**Fix.** Remove the cause listed above; on the real system each of these would have been a reset, as on Mars Pathfinder in 1997.
