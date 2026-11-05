# Pathfinder report: deadline_bug

Trace: `deadline_bug.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 27578 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f deadline_bug.kev`

## F1 [CRITICAL] Deadline misses: control missed 5 of 199 jobs (period 10 ms, worst release-to-completion 18 ms)

Window: 2724.8 - 2743.1 ms. Evidence events: #15743, #15859.

**Root cause.** Task control has a 10 ms period (from its pf_period markers) but 5 of 199 jobs finished more than one period after their release, worst 18 ms (job 170 started -0 ms late, events #15743, #15859). The misses overlap F2 (Priority inheritance working), which is the cause.

**Fix.** Fix the upstream cause first (see the linked finding). If the job legitimately needs more time, raise the period or shorten the work.

## F2 [WARNING] Long critical section: control waited up to 16 ms for a lock held by logger (inheritance worked, no inversion) and missed its deadline

Window: 2726.1 - 2742.1 ms. Evidence events: #15800.

**Root cause.** control waited up to 16 ms for a lock held by logger, but the kernel raised logger from priority 10 to 30 for the duration (events #15800), so no medium-priority thread could delay it. This is the desired behaviour, shown as evidence that the fix works.

**Fix.** Inheritance did its job (no medium-priority thread interfered) but the wait itself, 16 ms, is longer than the waiter's deadline budget. Shorten the critical section: copy the data under the lock and do the slow work (formatting, I/O) outside it.

Leads to: F1.
