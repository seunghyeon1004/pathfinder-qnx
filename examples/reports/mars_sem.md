# Pathfinder report: mars_sem

Trace: `mars_sem.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 27739 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f mars_sem.kev`

## F1 [CRITICAL] Priority inversion: bus_mgr (prio 30) blocked on a semaphore held by meteo (prio 10), starved by comms (prio 20)

Window: 3782.1 - 3939.6 ms. Evidence events: #18381, #18459, #18463, #18468, #18481.

**Root cause.** bus_mgr (priority 30) needed a POSIX semaphore that meteo (base priority 10) was holding, and had to wait. While it waited, meteo could not run: meteo stayed at priority 10 (it was never raised) and was kept off the CPU by comms, which runs at a priority between the two. That is unbounded priority inversion: the high-priority work was delayed by an unrelated medium-priority thread for up to 158 ms (150 ms of that with meteo ready but not scheduled), 10 times in this trace. Owner identified via pf_mark lock markers (semaphore: no kernel owner). Evidence: events #18381, #18459, #18463, #18468.

**Fix.** Do not use a POSIX semaphore as a lock. A semaphore has no owner in the kernel (SYNC_SEM_* events show owner:-4), so there is nobody to boost. Protect the shared data with a pthread mutex created with pthread_mutexattr_setprotocol(&attr, PTHREAD_PRIO_INHERIT) (the QNX default) or PTHREAD_PRIO_PROTECT with a ceiling of at least 30. Keep semaphores for signalling only.

Leads to: F2.

## F2 [CRITICAL] Deadline misses: bus_mgr missed 10 of 30 jobs (period 100 ms, worst release-to-completion 161 ms)

Window: 3783.5 - 3944.6 ms. Evidence events: #18456, #18638.

**Root cause.** Task bus_mgr has a 100 ms period (from its pf_period markers) but 10 of 30 jobs finished more than one period after their release, worst 161 ms (job 27 started -1 ms late, events #18456, #18638). The misses overlap F1 (Priority inversion), which is the cause.

**Fix.** Fix the upstream cause first (see the linked finding). If the job legitimately needs more time, raise the period or shorten the work.

Leads to: F3.

## F3 [CRITICAL] Watchdog fired 7 time(s): the system would have reset

Window: 1795.6 - 3642.2 ms. Evidence events: #9128, #11924, #12669, #13488, #16283, #17059.

**Root cause.** The application's watchdog reported a missed heartbeat 7 time(s) (events #9128, #11924, #12669, #13488). Preceded by F2.

**Fix.** Remove the cause listed above; on the real system each of these would have been a reset, as on Mars Pathfinder in 1997.
