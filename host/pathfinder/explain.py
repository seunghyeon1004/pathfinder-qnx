"""Deterministic root-cause / fix text. Every sentence is derived from numbers in the finding and cites event ids.
(An optional LLM layer in llm.py may rewrite the prose; it may not add facts, see llm.py.)"""


def _lab(model, key):
    t = model.threads.get(key)
    return t.label if t else "?"


def _ev(f, n=4):
    return ", ".join("#%d" % i for i in f.evidence[:n])


def explain(model, findings):
    byid = {f.id: f for f in findings}
    for f in findings:
        d = f.data
        if f.kind == "priority_inversion":
            W, O, M = (_lab(model, d["waiter"]), _lab(model, d["owner"]), _lab(model, d["interferer"]))
            kind = d["lock_kind"]
            lock = "a POSIX semaphore" if kind == "SEM" else "a mutex"
            f.root_cause = (
                "%s (priority %d) needed %s that %s (base priority %s) was holding, and had to wait. While it waited, %s could not run: "
                "%s stayed at priority %s (it was never raised) and was kept off the CPU by %s, which runs at a priority between the two. "
                "That is unbounded priority inversion: the high-priority work was delayed by an unrelated medium-priority thread for up to %.0f ms "
                "(%.0f ms of that with %s ready but not scheduled), %d times in this trace. Owner identified via %s. Evidence: events %s." % (
                    W, d["waiter_prio"], lock, O, _base(model, d["owner"]), O, O, d["owner_prio_during_block"], M,
                    d["worst_blocked_ms"], d["worst_starved_ms"], O, d["occurrences"], d["owner_via"], _ev(f)))
            if kind == "SEM":
                f.fix = ("Do not use a POSIX semaphore as a lock. A semaphore has no owner in the kernel (SYNC_SEM_* events show owner:-4), so there is nobody to boost. "
                         "Protect the shared data with a pthread mutex created with pthread_mutexattr_setprotocol(&attr, PTHREAD_PRIO_INHERIT) "
                         "(the QNX default) or PTHREAD_PRIO_PROTECT with a ceiling of at least %d. Keep semaphores for signalling only." % d["waiter_prio"])
            else:
                f.fix = ("This mutex was created with PTHREAD_PRIO_NONE, which turns priority inheritance off. Use PTHREAD_PRIO_INHERIT (the default on QNX; "
                         "just do not override it) so %s is raised to priority %d while %s waits, or PTHREAD_PRIO_PROTECT with a ceiling of at least %d. "
                         "Shorten the critical section as a second line of defence." % (O, d["waiter_prio"], W, d["waiter_prio"]))
        elif f.kind == "priority_inheritance":
            f.root_cause = ("%s waited up to %.0f ms for a lock held by %s, but the kernel raised %s from priority %s to %s for the duration (events %s), "
                            "so no medium-priority thread could delay it. This is the desired behaviour, shown as evidence that the fix works." % (
                                _lab(model, d["waiter"]), d["worst_blocked_ms"], _lab(model, d["owner"]), _lab(model, d["owner"]), d["base_prio"], d["boosted_prio"], _ev(f)))
            if f.cause_of:
                f.fix = ("Inheritance did its job (no medium-priority thread interfered) but the wait itself, %.0f ms, is longer than the waiter's deadline budget. "
                         "Shorten the critical section: copy the data under the lock and do the slow work (formatting, I/O) outside it." % d["worst_blocked_ms"])
                f.severity = "warning"
                f.title = "Long critical section: %s waited up to %.0f ms for a lock held by %s (inheritance worked, no inversion) and missed its deadline" % (
                    _lab(model, d["waiter"]), d["worst_blocked_ms"], _lab(model, d["owner"]))
            else:
                f.fix = "None needed. Keep critical sections short; the wait of %.0f ms is bounded by the owner's critical-section length." % d["worst_blocked_ms"]
        elif f.kind == "blocking":
            f.root_cause = "%s waited up to %.0f ms for a lock while %s kept running (no thread interfered). The delay is the owner's critical-section length." % (
                _lab(model, d["waiter"]), d["worst_blocked_ms"], _lab(model, d["owner"]))
            f.fix = "Shorten the critical section if this wait exceeds the waiter's deadline budget."
        elif f.kind == "deadline_miss":
            causes = [c for c in findings if f.id in c.cause_of]
            why = ""
            if causes:
                c = causes[0]
                why = " The misses overlap %s (%s), which is the cause." % (c.id, c.title.split(":")[0])
            f.root_cause = ("Task %s has a %.0f ms period (from its pf_period markers) but %d of %d jobs finished more than one period after their release, worst %.0f ms "
                            "(job %s started %.0f ms late, events %s).%s" % (
                d["task"], d["period_ms"], d["missed"], d["jobs"], d["worst_response_ms"], d["worst_job"], d["worst_start_delay_ms"], _ev(f), why))
            f.fix = "Fix the upstream cause first (see the linked finding). If the job legitimately needs more time, raise the period or shorten the work."
        elif f.kind == "watchdog_reset":
            causes = [c for c in findings if f.id in c.cause_of]
            f.root_cause = ("The application's watchdog reported a missed heartbeat %d time(s) (events %s)." % (d["count"], _ev(f)) +
                            (" Preceded by %s." % ", ".join(c.id for c in causes) if causes else ""))
            f.fix = "Remove the cause listed above; on the real system each of these would have been a reset, as on Mars Pathfinder in 1997."
        elif f.kind == "starvation":
            f.root_cause = ("%s (priority %d) was ready to run but waited up to %.0f ms because %s (priority %d) kept the CPU, %d times. "
                            "With fixed-priority scheduling this is expected whenever a higher-priority thread is busy; it is a problem only if %s has a deadline." % (
                                _lab(model, d["victim"]), d["victim_prio"], d["starved_ms"], _lab(model, d["hog"]), d["hog_prio"], d["occurrences"], _lab(model, d["victim"])))
            f.fix = "Bound the high-priority thread's CPU burst (sleep/yield or move work to a lower priority), use sporadic scheduling (SCHED_SPORADIC), or adaptive partitioning to guarantee a CPU budget."
        elif f.kind == "ipc_deadlock":
            cyc = f.data["cycle"]
            parts = []
            for k in cyc:
                parts.append("%s (%s, priority %d)" % (_lab(model, k), "waiting to send" if f.data["states"][k] == "BLK:SEND" else "waiting for a reply", f.data["prios"][k]))
            vic = ", ".join(_lab(model, k) for k in f.data["victims"])
            f.root_cause = ("Threads %s are blocked on each other in a cycle: each is inside a message handler and made a blocking MsgSend() to a channel whose "
                            "only server thread is itself blocked, so none of them can reach MsgReceive() again. %s They stayed blocked for %.0f ms in this trace. "
                            "Evidence: events %s." % (
                                "; ".join(parts), ("Clients blocked behind the cycle: %s." % vic) if vic else "", f.data["blocked_ms"], _ev(f, 6)))
            f.fix = ("Never make a blocking MsgSend() to another server from inside a handler while the original client is still waiting for a reply. Either (1) reply to the "
                     "client first and then notify the peer with a pulse (MsgSendPulse, never blocks), (2) hand the nested call to a worker thread, (3) impose a global "
                     "call order between servers so cycles cannot form, or (4) at minimum arm TimerTimeout() on the nested call and handle ETIMEDOUT.")
    return findings


def _base(model, key):
    t = model.threads.get(key)
    return t.base_prio if t else "?"
