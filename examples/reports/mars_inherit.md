# Pathfinder report: mars_inherit

Trace: `mars_inherit.kev` | QNX 8.0.0 x86pc on `qnxqemu` | 4 CPUs | 88828 events | tracelogger: `tracelogger -w -b 256 -k 16 -s 6 -f mars_inherit.kev`

## F1 [INFO] Priority inheritance working: meteo raised from 10 to 30 while bus_mgr waited

Window: 3083.7 - 3138.6 ms. Evidence events: #15861.

**Root cause.** bus_mgr waited up to 55 ms for a lock held by meteo, but the kernel raised meteo from priority 10 to 30 for the duration (events #15861), so no medium-priority thread could delay it. This is the desired behaviour, shown as evidence that the fix works.

**Fix.** None needed. Keep critical sections short; the wait of 55 ms is bounded by the owner's critical-section length.
