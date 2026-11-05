"""Detectors. Every finding lists the trace event ids (`evidence`) that prove it."""
import statistics
from dataclasses import dataclass, field

_PRIO = {}
LOCK_STATES = ("BLK:MUTEX", "BLK:SEM")


@dataclass
class Finding:
    id: str
    kind: str                 # priority_inversion | blocking | priority_inheritance | deadline_miss | watchdog_reset | starvation | ipc_deadlock
    severity: str             # critical | warning | info
    title: str
    t0: float                 # us (highlight window)
    t1: float
    threads: list = field(default_factory=list)       # [(pid,tid)]
    evidence: list = field(default_factory=list)      # event idx
    data: dict = field(default_factory=dict)
    instances: list = field(default_factory=list)     # [{t0,t1,...}]
    cause_of: list = field(default_factory=list)      # finding ids this one causes
    root_cause: str = ""
    fix: str = ""


class Config:
    min_block_ms = 5.0          # ignore lock waits shorter than this
    min_inversion_ms = 5.0      # owner READY (starved) at least this long while blocking a higher-prio thread
    starve_ms = 100.0
    min_latency_ms = 20.0
    deadlock_ms = 100.0         # SEND/REPLY-blocked at least this long before a cycle counts as a deadlock


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _prio_in(th, t0, t1):
    ps = [s.prio for s in th.segs if s.state == "RUN" and s.t1 > t0 and s.t0 < t1]
    return max(ps) if ps else (th.base_prio or 0)


def _running_in(model, t0, t1, exclude, lo, hi):
    """Threads RUNNING during [t0,t1] with priority strictly between lo and hi -> {key: us}"""
    res = {}
    for k, th in model.threads.items():
        if k in exclude or th.pid == 1:
            continue
        for s in th.segs:
            if s.state != "RUN" or s.t1 <= t0 or s.t0 >= t1:
                continue
            if lo < s.prio < hi:
                res[k] = res.get(k, 0.0) + _overlap(t0, t1, s.t0, s.t1)
                _PRIO[(k, id(res))] = max(_PRIO.get((k, id(res)), 0), s.prio)
    return res


def _lock_owner(model, waiter, seg, lockname):
    """Return (owner_key or None, how, sync_p, evidence_idx)."""
    best = None
    for (t, idx, who, sync_p, owner_tid) in model.mutex_waits:
        if who == waiter and seg.t0 - 300 <= t <= seg.t0 + 300:
            if best is None or abs(t - seg.t0) < abs(best[0] - seg.t0):
                best = (t, idx, sync_p, owner_tid)
    if best and best[3]:
        return ((waiter[0], best[3]), "kernel SYNC_MUTEX_LOCK owner field", best[2], best[1])
    # marker-assisted (needed for semaphores, which have no kernel-visible owner)
    want = None
    for (t, idx, who, code, text) in model.markers:
        if code == 3 and who == waiter and t <= seg.t0 + 300 and text.startswith("want "):
            want = (t, idx, text.split(" ", 1)[1])
    if want:
        holder = None
        for (t, idx, who, code, text) in model.markers:
            if code != 3 or t > seg.t0:
                continue
            if text == "acq " + want[2]:
                holder = (who, idx)
            elif text == "rel " + want[2] and holder and who == holder[0]:
                holder = None
        if holder and holder[0] != waiter:
            return (holder[0], "pf_mark lock markers (semaphore: no kernel owner)", None, holder[1])
    return (None, "owner unknown", best[2] if best else None, best[1] if best else None)


def detect_inversions(model, cfg):
    groups = {}
    inh = {}
    focus = focus_pids(model)
    for hk, H in model.threads.items():
        if H.pid == 1 or (focus is not None and H.pid not in focus):
            continue
        for seg in H.segs:
            if seg.state not in LOCK_STATES or (seg.t1 - seg.t0) < cfg.min_block_ms * 1000:
                continue
            ph = seg.prio
            owner, how, sync_p, ev_lock = _lock_owner(model, hk, seg, None)
            if owner == hk:
                continue
            kind = seg.state.split(":")[1]
            inst = {"t0": seg.t0, "t1": seg.t1, "waiter_prio": ph, "owner": owner, "lock": sync_p, "kind": kind,
                    "block_ev": seg.ev0, "lock_ev": ev_lock, "ready_us": 0.0, "interferers": {}, "owner_prio_max": None,
                    "owner_run_us": 0.0, "owner_blocked": {}, "how": how}
            if owner:
                L = model.threads.get(owner)
                pmax = 0
                if L:
                    for s in L.segs:
                        ov = _overlap(seg.t0, seg.t1, s.t0, s.t1)
                        if ov <= 0:
                            continue
                        pmax = max(pmax, s.prio)
                        if s.state == "RUN":
                            inst["owner_run_us"] += ov
                        elif s.state == "READY":
                            inst["ready_us"] += ov
                            for k, us in _running_in(model, max(seg.t0, s.t0), min(seg.t1, s.t1), {hk, owner}, s.prio, ph).items():
                                inst["interferers"][k] = inst["interferers"].get(k, 0) + us
                        else:
                            inst["owner_blocked"][s.state] = inst["owner_blocked"].get(s.state, 0) + ov
                    inst["owner_prio_max"] = pmax
                    inst["owner_base_prio"] = L.base_prio
                    if pmax >= ph > (L.base_prio or 0):
                        inh.setdefault((hk, owner, kind), []).append((inst, L))
            key = (hk, owner, kind)
            groups.setdefault(key, []).append(inst)
    findings = []
    n = 0
    for (hk, owner, kind), insts in groups.items():
        H = model.threads[hk]
        L = model.threads.get(owner) if owner else None
        bad = [i for i in insts if i["ready_us"] >= cfg.min_inversion_ms * 1000 and i["interferers"]]
        if bad:
            n += 1
            worst = max(bad, key=lambda i: i["ready_us"])
            # dominant interferer
            agg = {}
            for i in bad:
                for k, us in i["interferers"].items():
                    agg[k] = agg.get(k, 0) + us
            top = sorted(agg.items(), key=lambda kv: -kv[1])
            M = model.threads[top[0][0]]
            f = Finding(
                id="F%d" % n, kind="priority_inversion", severity="critical",
                title="Priority inversion: %s (prio %d) blocked on %s held by %s (prio %s), starved by %s (prio %d)" % (
                    H.label, worst["waiter_prio"], "a semaphore" if kind == "SEM" else "a mutex", L.label, worst["owner_base_prio"] if worst["owner_base_prio"] is not None else "?",
                    M.label, _prio_in(M, worst["t0"], worst["t1"])),
                t0=worst["t0"], t1=worst["t1"], threads=[hk, owner, top[0][0]],
                data={"waiter": hk, "owner": owner, "interferer": top[0][0], "lock_kind": kind, "sync_p": worst["lock"],
                      "owner_via": worst["how"], "occurrences": len(bad), "blocked_total_ms": sum(i["t1"] - i["t0"] for i in bad) / 1000,
                      "worst_blocked_ms": (worst["t1"] - worst["t0"]) / 1000, "worst_starved_ms": worst["ready_us"] / 1000,
                      "owner_prio_during_block": worst["owner_prio_max"], "waiter_prio": worst["waiter_prio"],
                      "inheritance_observed": False},
                instances=[{"t0": i["t0"], "t1": i["t1"], "ready_ms": i["ready_us"] / 1000, "blocked_ms": (i["t1"] - i["t0"]) / 1000} for i in bad],
                evidence=sorted({worst["block_ev"], worst["lock_ev"]} - {None}))
            # evidence: the owner's READY events inside the worst window + interferer running events
            L_ev = [s.ev0 for s in L.segs if s.state == "READY" and worst["t0"] <= s.t0 <= worst["t1"]][:3]
            M_ev = [s.ev0 for s in M.segs if s.state == "RUN" and worst["t0"] <= s.t0 <= worst["t1"]][:3]
            f.evidence += L_ev + M_ev
            findings.append(f)
        else:
            long = [i for i in insts if i["t1"] - i["t0"] >= cfg.min_block_ms * 1000]
            boosted = inh.get((hk, owner, kind))
            if boosted:
                n += 1
                inst, Lt = max(boosted, key=lambda x: x[0]["t1"] - x[0]["t0"])
                ev = []
                for t, p, idx in Lt.prio_changes:
                    if inst["t0"] <= t <= inst["t1"] and p >= inst["waiter_prio"]:
                        ev.append(idx)
                        break
                findings.append(Finding(
                    id="F%d" % n, kind="priority_inheritance", severity="info",
                    title="Priority inheritance working: %s raised from %s to %d while %s waited" % (Lt.label, inst["owner_base_prio"], inst["owner_prio_max"], H.label),
                    t0=inst["t0"], t1=inst["t1"], threads=[hk, owner],
                    data={"waiter": hk, "owner": owner, "base_prio": inst["owner_base_prio"], "boosted_prio": inst["owner_prio_max"],
                          "lock_kind": kind, "occurrences": len(boosted), "worst_blocked_ms": max(i[0]["t1"] - i[0]["t0"] for i in boosted) / 1000,
                          "sync_p": inst["lock"]},
                    instances=[{"t0": i[0]["t0"], "t1": i[0]["t1"], "blocked_ms": (i[0]["t1"] - i[0]["t0"]) / 1000, "ready_ms": i[0]["ready_us"] / 1000} for i in boosted],
                    evidence=[inst["block_ev"]] + ev))
            elif long and owner:
                n += 1
                worst = max(long, key=lambda i: i["t1"] - i["t0"])
                findings.append(Finding(
                    id="F%d" % n, kind="blocking", severity="info",
                    title="Bounded blocking: %s waits up to %.0f ms for %s (owner kept running, no inversion)" % (H.label, (worst["t1"] - worst["t0"]) / 1000, L.label),
                    t0=worst["t0"], t1=worst["t1"], threads=[hk, owner],
                    data={"waiter": hk, "owner": owner, "worst_blocked_ms": (worst["t1"] - worst["t0"]) / 1000, "lock_kind": kind, "occurrences": len(long)},
                    instances=[{"t0": i["t0"], "t1": i["t1"], "blocked_ms": (i["t1"] - i["t0"]) / 1000, "ready_ms": i["ready_us"] / 1000} for i in long],
                    evidence=[worst["block_ev"]]))
    return findings


def detect_deadlines(model, cfg, start_n):
    """Periodic jobs from pf_period markers (begin/end per task). Period = mean spacing of begin markers snapped to 5 ms;
    release_n = offset + n*period (offset = median); a job misses when end - release > period (deadline = period)."""
    findings = []
    tasks = {}
    for (t, idx, who, code, text) in model.markers:
        if code != 2:
            continue
        p = text.split()
        if len(p) < 3 or not p[2].isdigit():
            continue
        tasks.setdefault((p[1], who), {}).setdefault(int(p[2]), {})[p[0]] = (t, idx)
    n = start_n
    for (task, who), jobs in tasks.items():
        begins = sorted((v["begin"][0], k) for k, v in jobs.items() if "begin" in v)
        if len(begins) < 5:
            continue
        span = begins[-1][0] - begins[0][0]
        k_span = begins[-1][1] - begins[0][1]
        if k_span <= 0:
            continue
        period = round(span / k_span / 5000.0) * 5000.0
        if period <= 0:
            continue
        off = statistics.median(b - k * period for b, k in begins)
        missed, total = [], 0
        for k, v in jobs.items():
            if "begin" in v and "end" in v:
                total += 1
                rel = off + k * period
                resp = v["end"][0] - rel
                if resp > period * 1.02:
                    missed.append((k, rel, v["end"][0], resp, v["begin"][1], v["end"][1], v["begin"][0] - rel))
        if missed:
            n += 1
            worst = max(missed, key=lambda m: m[3])
            th = model.threads.get(who)
            findings.append(Finding(
                id="F%d" % n, kind="deadline_miss", severity="critical",
                title="Deadline misses: %s missed %d of %d jobs (period %.0f ms, worst release-to-completion %.0f ms)" % (th.label if th else task, len(missed), total, period / 1000, worst[3] / 1000),
                t0=worst[1], t1=worst[2], threads=[who],
                data={"task": task, "period_ms": period / 1000, "jobs": total, "missed": len(missed), "worst_response_ms": worst[3] / 1000, "worst_job": worst[0],
                      "worst_start_delay_ms": worst[6] / 1000},
                instances=[{"t0": m[1], "t1": m[2], "response_ms": m[3] / 1000, "job": m[0]} for m in sorted(missed)],
                evidence=[worst[4], worst[5]]))
    return findings


def detect_watchdog(model, start_n):
    resets = [(t, idx, text) for (t, idx, who, code, text) in model.markers if code == 4 and "WATCHDOG" in text.upper()]
    if not resets:
        return []
    f = Finding(id="F%d" % (start_n + 1), kind="watchdog_reset", severity="critical",
                title="Watchdog fired %d time(s): the system would have reset" % len(resets),
                t0=resets[0][0], t1=resets[-1][0] + 1000.0,
                data={"count": len(resets)}, instances=[{"t0": t, "t1": t + 1000.0, "text": s} for t, _, s in resets],
                evidence=[i for _, i, _ in resets][:6])
    return [f]


def link_causes(findings):
    for a in findings:
        if a.kind == "starvation":
            for b in findings:
                if b.kind == "deadline_miss" and a.data["victim"] in b.threads and \
                        any(_overlap(i["t0"], i["t1"], j["t0"], j["t1"]) > 0 for i in a.instances for j in b.instances):
                    a.cause_of.append(b.id)
                    a.severity = "critical"
    """inversion -> deadline_miss -> watchdog_reset, linked by time overlap."""
    inv = [f for f in findings if f.kind in ("priority_inversion", "blocking", "priority_inheritance")]
    miss = [f for f in findings if f.kind == "deadline_miss"]
    wd = [f for f in findings if f.kind == "watchdog_reset"]
    for a in inv:
        for b in miss:
            if any(_overlap(i["t0"], i["t1"], j["t0"], j["t1"]) > 0 for i in a.instances for j in b.instances):
                a.cause_of.append(b.id)
    for a in miss:
        for b in wd:
            if any(j["t0"] >= i["t0"] and j["t0"] <= i["t1"] + 200_000 for i in a.instances for j in b.instances):
                a.cause_of.append(b.id)


def focus_pids(model):
    """Workload processes: those that emitted pf_mark markers (else everything except the kernel)."""
    if model.has_pf:
        return {w[0] for (_, _, w, _, _) in model.markers if w}
    return None


def _edges_at(model, T, min_us):
    """Wait-for edges among threads that have been SEND- or REPLY-blocked for at least min_us at time T."""
    blocked = {}
    for k, th in model.threads.items():
        for sg in th.segs:
            if sg.state in ("BLK:SEND", "BLK:REPLY") and sg.t0 <= T - min_us and sg.t1 >= T:
                blocked[k] = sg
                break
    edges = {}
    for k, sg in blocked.items():
        sends = [x for x in model.sends.get(k, []) if x[0] <= sg.t0 + 50]
        if not sends:
            continue
        t, idx, rcvid, srv_pid, coid = sends[-1]
        tgt = set()
        if sg.state == "BLK:REPLY":
            r = model.rec.get(rcvid)
            if r:
                tgt.add(r[0])
        else:
            chan = model.coid_chan.get((k[0], coid))
            if chan:
                tgt |= set(model.recv.get((chan[0] or k[0], chan[1]), ()))
        edges[k] = {x for x in tgt if x in blocked and x != k}
    return blocked, edges


def _cycle(edges):
    color = {}
    stack = []

    def dfs(u):
        color[u] = 1
        stack.append(u)
        for v in sorted(edges.get(u, ())):
            if color.get(v, 0) == 0:
                r = dfs(v)
                if r:
                    return r
            elif color[v] == 1:
                return stack[stack.index(v):]
        stack.pop()
        color[u] = 2
        return None
    for u in sorted(edges):
        if color.get(u, 0) == 0:
            r = dfs(u)
            if r:
                return r
    return None


def detect_ipc_deadlock(model, cfg, start_n):
    min_us = cfg.deadlock_ms * 1000
    cands = sorted({sg.t0 + min_us for th in model.threads.values() for sg in th.segs
                    if sg.state in ("BLK:SEND", "BLK:REPLY") and sg.t1 - sg.t0 >= min_us})
    seen, out, n = set(), [], start_n
    for T in cands:
        blocked, edges = _edges_at(model, T, min_us)
        cyc = _cycle(edges)
        if not cyc or frozenset(cyc) in seen:
            continue
        seen.add(frozenset(cyc))
        # victims: blocked threads that (transitively) wait on the cycle
        victims = set()
        for k in blocked:
            if k in cyc:
                continue
            todo, vis = [k], set()
            while todo:
                u = todo.pop()
                if u in vis:
                    continue
                vis.add(u)
                if u in cyc and u != k:
                    victims.add(k)
                    break
                todo += list(edges.get(u, ()))
        members = list(cyc) + sorted(victims)
        t0 = max(blocked[k].t0 for k in members)
        t1 = min(blocked[k].t1 for k in members)
        names = " -> ".join(model.threads[k].label for k in cyc + [cyc[0]])
        ev = [blocked[k].ev0 for k in cyc]
        for k in cyc:
            sends = [x for x in model.sends.get(k, []) if x[0] <= blocked[k].t0 + 50]
            if sends:
                ev.append(sends[-1][1])
        n += 1
        out.append(Finding(
            id="F%d" % n, kind="ipc_deadlock", severity="critical",
            title="IPC deadlock: %s (%d threads in a wait-for cycle, %d more blocked behind it)" % (names, len(cyc), len(victims)),
            t0=t0, t1=t1, threads=list(cyc) + sorted(victims),
            data={"cycle": cyc, "victims": sorted(victims), "blocked_ms": (t1 - t0) / 1000.0,
                  "states": {k: blocked[k].state for k in members}, "prios": {k: blocked[k].prio for k in members}},
            instances=[{"t0": t0, "t1": t1}], evidence=sorted(set(ev))))
    return out


def detect_starvation(model, cfg, start_n, skip_threads):
    """Long READY waits. Under fixed-priority scheduling a low-priority thread waiting for a higher-priority one is expected,
    so this is reported as information unless the victim is also blocking someone (that case is the inversion detector's)."""
    focus = focus_pids(model)
    agg = {}
    for k, th in model.threads.items():
        if th.pid == 1 or k in skip_threads or (focus is not None and th.pid not in focus):
            continue
        for s in th.segs:
            if s.state == "READY" and (s.t1 - s.t0) >= cfg.starve_ms * 1000 and s.prio > 0:
                run = _running_in(model, s.t0, s.t1, {k}, -1, 1000)
                if not run:
                    continue
                top = max(run.items(), key=lambda kv: kv[1])
                if top[1] < 0.6 * (s.t1 - s.t0):
                    continue
                agg.setdefault((k, top[0]), []).append((s, _prio_in(model.threads[top[0]], s.t0, s.t1)))
    out = []
    n = start_n
    for (k, hk), lst in agg.items():
        th, hog = model.threads[k], model.threads[hk]
        worst = max(lst, key=lambda x: x[0].t1 - x[0].t0)[0]
        hp = max(x[1] for x in lst)
        sev = "info" if hp > worst.prio else "warning"
        n += 1
        out.append(Finding(
            id="F%d" % n, kind="starvation", severity=sev,
            title="CPU starvation: %s (prio %d) kept off the CPU up to %.0f ms by %s (prio %d), %d times" % (th.label, worst.prio, (worst.t1 - worst.t0) / 1000, hog.label, hp, len(lst)),
            t0=worst.t0, t1=worst.t1, threads=[k, hk],
            data={"victim": k, "hog": hk, "victim_prio": worst.prio, "hog_prio": hp, "starved_ms": (worst.t1 - worst.t0) / 1000, "occurrences": len(lst)},
            instances=[{"t0": x[0].t0, "t1": x[0].t1, "starved_ms": (x[0].t1 - x[0].t0) / 1000} for x in lst],
            evidence=[worst.ev0]))
    return out


def analyze(model, cfg=None):
    cfg = cfg or Config()
    findings = detect_inversions(model, cfg)
    findings += detect_ipc_deadlock(model, cfg, len(findings))
    findings += detect_deadlines(model, cfg, len(findings))
    findings += detect_watchdog(model, len(findings))
    owners = {f.data["owner"] for f in findings if f.kind in ("priority_inversion", "blocking", "priority_inheritance") and f.data.get("owner")}
    findings += detect_starvation(model, cfg, len(findings), owners)
    order = {"critical": 0, "warning": 1, "info": 2}
    krank = {"priority_inversion": 0, "ipc_deadlock": 0, "deadline_miss": 1, "watchdog_reset": 2}
    findings.sort(key=lambda f: (order[f.severity], krank.get(f.kind, 5), f.t0))
    for i, f in enumerate(findings):
        f.id = "F%d" % (i + 1)
    link_causes(findings)
    return findings
