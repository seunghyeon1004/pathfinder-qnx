# Devpost submission text (QNX Everywhere Hackathon)

Fill the form with the blocks below. Fields in the QNX rules: repo URL, text description, demo video (YouTube, public, under 3 min),
build and run instructions (QNX version, target, toolchain), one category, optional codelab URL.

## Project name
Pathfinder

## Elevator pitch (one line)
A real-time trace doctor for QNX 8.0: it reads kernel traces and tells you which priority inversion, IPC deadlock or starvation broke your system, why, and how to fix it, with every claim tied to kernel events.

## Category
Developer Tooling & Host Tools

## Links
* Code (Apache-2.0): https://github.com/seunghyeon1004/pathfinder-qnx   (make public before submitting)
* Demo video (YouTube, public, 1:50): TODO paste the link returned by the uploader (links.txt `qnx:`)
* Codelab / tutorial (Best Codelab / Tutorial bonus): https://github.com/seunghyeon1004/pathfinder-qnx/blob/master/docs/CODELAB.md
* Build and run instructions: https://github.com/seunghyeon1004/pathfinder-qnx/blob/master/docs/RUN.md

## Text description (paste into "What it does")
In 1997 the Mars Pathfinder lander kept resetting because a low-priority task held a lock that a high-priority task needed, while a medium-priority task kept the CPU. Engineers needed days to find it in a trace. Pathfinder finds it in seconds.

Pathfinder is a developer tool for QNX 8.0. On the target, `tracelogger -w` records the instrumented kernel's events (every thread state change with its priority, mutex and semaphore waits, message passing). On the host, a standard-library-only Python analyzer parses `traceprinter` output and:

* finds **priority inversions** and reports the whole blocking chain (high-priority waiter -> lock -> owner -> the unrelated thread that starved the owner), the duration, and whether priority inheritance was observed;
* finds **IPC deadlocks** (a wait-for cycle of MsgSend/MsgReceive between servers, with the clients stuck behind it) using rcvid, coid and chid matching;
* finds **missed deadlines** of periodic tasks, **CPU starvation**, and **application watchdog resets**, and links them into a causal chain (inversion -> deadline miss -> watchdog reset);
* writes a single-file **interactive HTML timeline** (zoom, pan, click a finding to highlight it, evidence events one click away), a Markdown report and JSON;
* **proves a fix** by A/B traces: with `PTHREAD_PRIO_INHERIT` the report shows the lock owner boosted from 10 to 30 and no deadline misses;
* optionally adds an LLM-written narrative in which every claim must cite trace event ids (claims with unknown ids are dropped).

It ships with four scenario programs for QNX 8.0 (Mars Pathfinder inversion with a `PTHREAD_PRIO_NONE` mutex and with a semaphore, a two-server IPC deadlock, a long-critical-section deadline miss, a CPU-starvation case), each in a bug and a fix mode, and ten real traces recorded on QNX 8.0 with their reports.

## How it uses QNX (evidence of QNX use)
* Runs on **QNX SDP 8.0** (QNX Everywhere license): QEMU x86_64 quick-start image, kernel `procnto-smp-instr`, `uname`: `QNX qnxqemu 8.0.0 2026/06/05 x86pc x86_64`. Built with `qcc` 12.2.0 (`-Vgcc_ntox86_64`; sources also build for `aarch64le`).
* Native QNX features: instrumented-kernel tracing (`tracelogger`, `traceprinter`, wide events), user trace events (`TraceEvent`), `SCHED_FIFO` priorities, `PTHREAD_PRIO_NONE/INHERIT/PROTECT`, `_NTO_TCTL_RUNMASK`, message passing (`ChannelCreate`, `MsgSend`, `MsgReceive`, `MsgReply`, `MsgSendPulse`, `TimerTimeout`).
* Every claim in the repo is backed by a trace recorded on the QNX 8.0 target; `scripts/e2e.sh` rebuilds, runs and asserts all of them (10 of 10 pass), `host/tests` runs 12 tests on the committed real traces.

## Build and run instructions (summary; full: docs/RUN.md)
* QNX version: SDP 8.0. Target: QEMU x86_64 quick-start image (no KVM needed). Toolchain: `qcc` 12.2.0.
* `source ~/qnx800/qnxsdp-env.sh && make -C target`, `scripts/qnx-vm.sh start`, `scripts/pf-run.sh mars none 3`, `python3 -m pathfinder analyze examples/traces/mars_none.txt.gz --out report` (from `host/`).
* No QNX at hand: `python3 -m unittest discover host/tests` analyzes the committed real traces with Python only.

## How we built it
Wrote the scenario programs in C against the QNX 8.0 APIs, recorded kernel traces on the real image, studied the `traceprinter` event schema (thread state events carry priority; contended `SYNC_MUTEX_LOCK` carries the owner; `SND_MESSAGE`/`REC_MESSAGE` pair messages by rcvid), and built a parser, a thread-state model, four detectors and an HTML renderer around it. The SDP only runs on x86 Linux/Windows hosts, so on an Apple Silicon Mac we used an amd64 container for the toolchain and QEMU software emulation for the target; the scripts for that are in the repo.

## Challenges
* QNX mutexes inherit priority by default, so the Mars bug needs an explicit `PTHREAD_PRIO_NONE` or a semaphore; the tool explains this instead of giving generic advice.
* Uncontended locks never enter the kernel and semaphores have no owner, so lock ownership comes from kernel owner fields where available and from lightweight markers otherwise.
* `TimerTimeout()` arms only the next blocking call; a trace marker between it and `MsgSend` silently disabled our deadlock timeout (found with the tool's own trace).

## Accomplishments
Real reproduction of the Pathfinder failure on QNX 8.0 with an automatic, evidence-linked diagnosis, an A/B fix proof, an IPC deadlock detector, and a fully scripted end-to-end run with real traces.

## What's next
Resource-manager and pulse-aware wait-for graphs, aarch64 traces on Raspberry Pi, Momentics `.kev` import, CI integration (non-zero exit on critical findings already works).

## Built with
C, qcc, QNX Neutrino 8.0, tracelogger/traceprinter, Python 3 (standard library), QEMU, Docker (SDP host on Apple Silicon).

## AI use disclosure
Developed with an AI coding assistant (Claude). All code was run and verified on QNX 8.0; the demo video uses synthetic narration and no music.
