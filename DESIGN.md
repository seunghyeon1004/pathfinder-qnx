# Pathfinder - a real-time trace doctor for QNX 8.0

Category: Developer Tooling & Host Tools (QNX Everywhere hackathon).
Target: QNX SDP 8.0, x86_64, QEMU quick-start image (also builds for aarch64le). Toolchain: `qcc` 12.2.0 (`gcc_ntox86_64`).

## 1. Problem

Real-time bugs (priority inversion, IPC deadlock, missed deadlines, starvation) leave a precise footprint in the QNX
instrumented kernel's event stream, but reading `traceprinter` output by hand means scanning tens of thousands of lines.
The 1997 Mars Pathfinder resets are the canonical example: a low-priority task held a lock, a medium-priority task kept the CPU,
the high-priority bus task starved, the watchdog fired. Pathfinder turns a `.kev` trace into: findings, the blocking chain that
causes each one, a plain-language root cause, a verified fix, and an interactive timeline.

## 2. What was verified on the real QNX 8.0 image (not assumptions)

| Fact | Evidence |
|---|---|
| Image kernel is instrumented (`procnto-smp-instr`), `tracelogger` ships in `/system/bin`, needs root (`sudo`, qnxuser/qnxuser) | `tracelogger -s 2 -f t.kev` -> 107 KB .kev; unprivileged run: "tracelog_start: Operation not permitted" |
| `traceprinter` (SDP host + target builds) prints one line per event; header gives `TRACE_CYCLES_PER_SEC`, CPU count | `traceprinter -f t.kev` |
| In wide mode (`tracelogger -w`) every THREAD state event carries `pid tid priority policy` | `THREAD :THMUTEX pid:1298461 tid:4 priority:30 policy:1` |
| Thread blocking states are visible: THMUTEX, THSEM, THCONDVAR, THSEND, THRECEIVE, THREPLY, THNANOSLEEP, THREADY, THRUNNING | trace histogram |
| Contended mutex lock produces `KER_CALL SYNC_MUTEX_LOCK sync_p:<addr> owner:<word>` (uncontended locks stay in user space and are not traced) | spike trace |
| Default mutex protocol is `PTHREAD_PRIO_INHERIT` (QNX docs `pthread_mutexattr_init`); `PTHREAD_PRIO_NONE` disables inheritance | SDP local docs |
| Message passing: the receiving server thread takes the sender's priority unless the channel has `_NTO_CHF_FIXED_PRIORITY` | `ChannelCreate()` docs |
| Target image has python3.14, gcc, cmake, git: the analyzer can also run on the target itself | `ls /usr/bin` on the VM |

Priority inheritance is visible in the trace as a *change of the owner's reported `priority`* while it runs; that is how the tool
proves the fix works (A/B: same workload, `PRIO_NONE` vs `PRIO_INHERIT`).

## 3. Architecture

```
 QNX 8.0 target (QEMU)                          host (macOS/Linux)
 +--------------------------------+             +-----------------------------------------+
 | scenarios/ (C, qcc)            |             | pathfinder (Python 3, stdlib only)      |
 |  mars      L/M/H + mutex       |  .kev       |  parse  : traceprinter text -> events   |
 |  ipc_dead  two servers         | ----------> |  model  : per-thread state intervals    |
 |  deadline  periodic + jitter   |  traceprint |  detect : inversion / deadlock /        |
 |  starve    CPU hog vs worker   |             |           deadline / starvation         |
 | pf_mark.h  user trace markers  |             |  explain: rules (+ optional LLM)        |
 | tracelogger -w (instr. kernel) |             |  render : report.html, report.md, .json |
 +--------------------------------+             +-----------------------------------------+
```

* **On-target (C, `target/`)**: scenario generators (each has a `--bug` and `--fix` mode), `pf_mark.h` (thin wrapper over
  `TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT)` to label threads/periods/locks in the same kernel stream), `pf-capture.sh`
  (runs tracelogger -w around a scenario, then `traceprinter`).
* **Host analyzer (Python 3, no third-party deps, `host/pathfinder/`)**:
  1. `parse`: traceprinter text -> typed events (index, time in microseconds from cycle counter, cpu, class, event, fields).
  2. `model`: thread table (pid, tid, name from PROCTHREAD_NAME / markers), per-thread intervals
     (RUNNING / READY / BLOCKED:{MUTEX,SEM,CONDVAR,SEND,REPLY,RECEIVE,SLEEP}) with priority at every change.
  3. `detect` (every finding carries the list of event indices that prove it):
     * **Priority inversion**: thread H blocked on a lock/IPC whose owner L has lower priority, L is READY (not RUNNING) while some
       thread M with prio(L) < prio(M) is RUNNING, for longer than a threshold. Reports blocking chain H -> lock -> L,
       the interferer M, duration, and whether the owner's priority was boosted (inheritance observed or absent).
     * **IPC deadlock**: wait-for graph from SEND/REPLY-blocked threads to the thread that must reply/receive (via
       `coid -> pid/chid` from CONNECT_ATTACH / MSG_SENDV events); cycle detection; reports the cycle.
     * **Missed deadline / jitter**: periodic markers (`pf_period_begin/end`) or inferred periodicity from THRUNNING of a thread;
       latency spikes from READY->RUNNING time.
     * **CPU starvation**: thread READY longer than N ms while only other-priority threads run on all CPUs.
  4. `explain`: deterministic rule templates (always on, no network) produce root cause + fix. Optional `--llm`
     sends only the structured findings (never the raw trace) to the Anthropic API and asks for a plain-language narrative in JSON;
     the response is validated: every claim must cite existing event indices, otherwise it is discarded and the rule text is kept.
  5. `render`: one self-contained `report.html` (inline SVG/JS, no CDN): lanes per thread colored by state, priority line,
     lock ownership arrows, findings sidebar that highlights the exact interval, plus `report.md` and `findings.json`.
* **Fix verification**: `pf-ab` runs a scenario twice (`--bug`, `--fix`), analyzes both, prints a before/after table.
  QNX-specific accuracy: on QNX a plain `pthread_mutex_t` already inherits priority, so the *bug* modes use the things that
  do not: an explicit `PTHREAD_PRIO_NONE` mutex, a binary POSIX semaphore used as a lock, and a `_NTO_CHF_FIXED_PRIORITY`
  channel; the *fix* modes are `PTHREAD_PRIO_INHERIT` (default), `PTHREAD_PRIO_PROTECT`, and a normal channel. The tool says
  this explicitly in the explanation. (Semaphore non-inheritance is asserted only after the trace of our own run shows it.)

## 4. Scenarios

1. `mars` - L(10) takes lock, M(20) busy CPU burst, H(30) "bus task" wants the lock and has a deadline; a watchdog thread (40)
   expects H's heartbeat every 100 ms and prints `WATCHDOG RESET` when missed. Modes: `none`, `sem`, `inherit`, `protect`.
2. `ipc_deadlock` - process A and B each run a resource-manager-style server thread and a client thread; each server calls the
   other during request handling (MsgSend while inside handler) -> cycle. Fix: reply first / use pulses.
3. `deadline` - 10 ms periodic control loop with an occasional blocking call (e.g. logging via slow `write`), showing latency spikes.
4. `starve` - priority-N busy loop with SCHED_FIFO vs a lower-priority worker; shows starvation, fix by `SCHED_RR`/priority change.

## 5. Evidence for judges

* `make` builds all target programs with `qcc -Vgcc_ntox86_64` (and aarch64le); `docs/RUN.md` gives QEMU boot + ssh commands.
* `examples/` holds committed real `.kev` traces recorded on the QNX 8.0 VM plus the generated HTML/MD reports.
* `scripts/e2e.sh` does boot -> push -> trace -> analyze -> assert (CI-like acceptance run, exit code non-zero on failure).
* Video (<3 min): terminal split: QEMU QNX running `mars --bug`, watchdog reset prints, `pathfinder analyze`, open HTML timeline,
  click the finding, run `--fix`, show clean report.

## 6. Scope control / risks

* Event schema differences (traceprinter text) are isolated in `parse.py`; tests run against committed real traces.
* Owner identification of a contended mutex uses the `owner` word in `SYNC_MUTEX_LOCK` (low bits = owner tid); semaphores have
  no owner in the kernel, so for the sem scenario the owner comes from `pf_mark` lock markers (documented limitation).
* IPC wait-for graph is the highest-risk item; if coid resolution proves fragile we fall back to marker-assisted graph and say so.
* LLM layer is optional and off by default; no key is stored in the repo.
* Built with AI assistance (disclosed in README).
