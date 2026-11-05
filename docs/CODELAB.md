# Codelab: catch a priority inversion on QNX 8.0 with the instrumented kernel (20 minutes)

You will build a tiny program with `qcc`, run it on QNX 8.0, record a **kernel event trace** with `tracelogger`, read the
trace with `traceprinter`, see a **priority inversion** with your own eyes, fix it, and prove the fix from the trace.
Everything below was run on QNX SDP 8.0 (QEMU x86_64 quick-start image, kernel `procnto-smp-instr`); the outputs are real.
Authored for the QNX Everywhere Hackathon (November 2026).

**What you learn**
1. Build and deploy a C program for QNX 8.0 with `qcc`.
2. Pin threads to a CPU and use real-time (`SCHED_FIFO`) priorities.
3. Record and read kernel events: thread states (`THRUNNING`, `THREADY`, `THMUTEX`) and priorities.
4. What `PTHREAD_PRIO_NONE` and `PTHREAD_PRIO_INHERIT` do, and how to *see* priority inheritance working.

## 0. Prerequisites
* QNX SDP 8.0 with the free non-commercial license (QNX Everywhere) and the QEMU quick-start image
  (`com.qnx.qnx800.quickstart.qemu`; see the QNX Everywhere docs, or `docs/RUN.md` in this repository for a scripted setup).
* `ssh` access to the running image (default user `qnxuser`, password `qnxuser`).
* The SDP host tools are x86_64 Linux/Windows only (SDP 8.0 does not run on macOS or ARM hosts).

## 1. Boot and check that you have an instrumented kernel
```
$ uname -a
QNX qnxqemu 8.0.0 2026/06/05-16:26:03EDT x86pc x86_64
$ ls /proc/boot | grep procnto
procnto-smp-instr
$ ls /system/bin/tracelogger
/system/bin/tracelogger
```
`procnto-smp-instr` is the **instrumented** microkernel: it can emit an event for every scheduling decision. `tracelogger` collects them
(root only).

## 2. The program: three threads and one lock
Save [`docs/codelab/inversion.c`](codelab/inversion.c). It creates L (priority 10, holds the lock for 60 ms), M (priority 20, burns CPU
for 150 ms, does not use the lock) and H (priority 30, wants the lock). All threads are pinned to CPU 0 with
`ThreadCtl(_NTO_TCTL_RUNMASK, ...)`, so the result does not depend on SMP timing. The lock protocol is chosen by the command line:

```c
pthread_mutexattr_setprotocol(&at, inherit ? PTHREAD_PRIO_INHERIT : PTHREAD_PRIO_NONE);
```

Build and copy it to the target:
```
$ source ~/qnx800/qnxsdp-env.sh
$ qcc -Vgcc_ntox86_64 -o inversion inversion.c
$ scp -P 2222 inversion qnxuser@localhost:/data/home/qnxuser/
```

## 3. Run it without priority inheritance, under tracelogger
On the target (as root; `-w` = wide events, which carry the thread priority):
```
$ sudo sh -c 'tracelogger -w -s 3 -f inv_none.kev & sleep 1; ./inversion none; wait'
H waited 133 ms for the lock
```
H is the highest-priority thread, yet it waited 133 ms for a lock that L holds for only 60 ms. That is the inversion.
Copy `inv_none.kev` to the host and print it: `traceprinter -n -f inv_none.kev > inv_none.txt` (the SDP's `traceprinter`, also in the image's SDP target folder).

## 4. Read the trace
Search for H's block (`THMUTEX` is the state "blocked on a mutex"), then look at who gets the CPU. This is the real excerpt
(thread ids replaced by names, times in ms from the start of the trace):

```
1076.7  H  THRUNNING priority:30         H runs, asks for the lock ...
1076.8  H  THMUTEX   priority:30         ... and BLOCKS: L owns the mutex
1076.8  M  THRUNNING priority:20         M (not involved with the lock) takes the CPU
        ... 133 ms pass ...
1209.8  M  THREADY   priority:20         M finally finishes its burst
1209.8  L  THRUNNING priority:10         only now can L run and release the lock
1209.9  H  THRUNNING priority:30         and H gets the lock
```
Why: L is READY at priority 10 but M (20) preempts it, and H (30) is waiting for L. The kernel has no reason to run L. The fact that **L's
priority stayed at 10** while H (30) was blocked on it is the signature of an inversion without inheritance.

## 5. Fix: priority inheritance
`PTHREAD_PRIO_INHERIT` tells the kernel to raise the lock owner to the priority of the highest waiter. (On QNX this is also the
**default** protocol of a mutex; the bug above needed `PTHREAD_PRIO_NONE` on purpose.)
```
$ sudo sh -c 'tracelogger -w -s 3 -f inv_inherit.kev & sleep 1; ./inversion inherit; wait'
H waited 7 ms for the lock
```
133 ms became 7 ms. Look at the trace the same way:
```
1087.7  L  THREADY   priority:30         L is ready and now runs at priority 30 (it inherited H's priority)
1087.7  H  THMUTEX   priority:30         H blocks on the mutex
1087.7  L  THRUNNING priority:30         L runs at once, M cannot preempt it
1094.7  H  THREADY   priority:30         7 ms later L unlocks and H continues
1094.7  L  THRUNNING priority:10         L drops back to its own priority 10
```
The **priority change of the owner** is how you prove inheritance from a trace: 10 -> 30 while H waits, back to 10 afterwards.

## 6. Let a tool read the trace for you (optional)
```
$ python3 -m pathfinder analyze inv_none.txt --out report      # from host/ in this repository
```
Pathfinder reports the blocking chain (H waits for L, L is kept off the CPU by M), the owner's unchanged priority and the wait time,
and for `inv_inherit.txt` it reports "priority inheritance working: L raised from 10 to 30".

## 7. Exercises 
1. Replace the mutex with a binary POSIX semaphore (`sem_wait`/`sem_post`). Does the inversion come back? (It does: a semaphore has no owner, so there is nobody to boost.)
2. Use `PTHREAD_PRIO_PROTECT` with `pthread_mutexattr_setprioceiling(&at, 30)`. Where does L's priority change in the trace now?
3. Remove `ThreadCtl(_NTO_TCTL_RUNMASK, ...)` on a 4-CPU image. Why does the inversion disappear or shrink?
4. Add `TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, 1, "got lock")` after the lock and find your marker in the `traceprinter` output.

## Troubleshooting
* `tracelog_start: Operation not permitted`: run `tracelogger` as root (`sudo`).
* Empty trace: the kernel must be `procnto-smp-instr` (the quick-start image is).
* `-lpthread` link errors: pthreads are part of `libc` on QNX; do not pass `-lpthread`.
