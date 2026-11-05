"""Turn the flat event list into threads, state intervals, priorities, lock/IPC facts."""
from collections import defaultdict
from dataclasses import dataclass, field

BLOCK_STATES = {
    "THMUTEX": "MUTEX", "THSEM": "SEM", "THCONDVAR": "CONDVAR", "THSEND": "SEND", "THRECEIVE": "RECEIVE",
    "THREPLY": "REPLY", "THNANOSLEEP": "SLEEP", "THWAITTHREAD": "JOIN", "THWAITPAGE": "PAGE", "THSIGSUSPEND": "SIGSUSPEND",
    "THSIGWAITINFO": "SIGWAIT", "THWAITCTX": "WAITCTX", "THSTOPPED": "STOPPED", "THJOIN": "JOIN", "THINTR": "INTR",
    "THNET_SEND": "NETSEND", "THNET_REPLY": "NETREPLY", "THMUON_MUTEX": None,
}
# THMUON_MUTEX = "mutex owner changed/woken" bookkeeping; not a state change we draw


@dataclass
class Seg:
    t0: float
    t1: float
    state: str        # RUN, READY, or BLK:<kind>
    prio: int
    cpu: int
    ev0: int          # event idx that started this segment


@dataclass
class Thread:
    pid: int
    tid: int
    name: str = ""
    segs: list = field(default_factory=list)
    prio_changes: list = field(default_factory=list)   # (t, prio, idx)
    created: float = None
    ended: float = None
    base_prio: int = None

    @property
    def key(self): return (self.pid, self.tid)

    @property
    def label(self):
        return self.name or "pid%d.t%d" % (self.pid, self.tid)


class Model:
    def __init__(self, hdr, events):
        self.hdr, self.events = hdr, events
        self.events.sort(key=lambda e: (e.cyc, e.idx))
        self.byidx = {e.idx: e for e in events}
        self.threads = {}
        self.procs = {}                    # pid -> name
        self.cpu_cur = {}                  # cpu -> (pid,tid) currently running
        self.markers = []                  # (t, idx, thread key, code, text)
        self.mutex_waits = []              # (t, idx, waiter, sync_p, owner_tid)
        self.recv = defaultdict(set)       # (pid, chid) -> {(pid, tid)} that did MsgReceive
        self.coid_chan = {}                # (pid, coid) -> (srv_pid, chid)
        self.recv_chan = {}                # thread -> chid of its last MsgReceive call
        self.t_end = events[-1].t if events else 0.0
        self.has_pf = False                # pathfinder markers present
        self.sends = defaultdict(list)     # sender key -> [(t, idx, rcvid, srv_pid, coid)]
        self.rec = {}                      # rcvid -> (receiver key, t, idx)
        self.replied = {}                  # (pid,tid) -> t of last REPLY_MESSAGE to it
        self._last_coid = {}
        self._pending_attach = {}
        self._build()

    def th(self, pid, tid):
        k = (pid, tid)
        if k not in self.threads:
            self.threads[k] = Thread(pid, tid)
        return self.threads[k]

    def caller(self, ev):
        """Thread that executed a kernel call / user event: whoever runs on that CPU just before it."""
        return self.cpu_cur.get(ev.cpu)

    def _build(self):
        open_seg = {}                      # thread key -> Seg (open)
        for ev in self.events:
            c, n, f = ev.cls, ev.name, ev.f
            if c == "THREAD" and "pid" in f and "tid" in f:
                k = (f["pid"], f["tid"])
                t = self.th(*k)
                if n == "THCREATE":
                    t.created = ev.t
                    continue
                if n in ("THDESTROY", "THDEAD"):
                    seg = open_seg.pop(k, None)
                    if seg:
                        seg.t1 = ev.t
                    t.ended = ev.t
                    continue
                if n == "THMUON_MUTEX":
                    continue
                if n == "THRUNNING":
                    state = "RUN"
                    self.cpu_cur[ev.cpu] = k
                elif n == "THREADY":
                    state = "READY"
                elif n in BLOCK_STATES and BLOCK_STATES[n]:
                    state = "BLK:" + BLOCK_STATES[n]
                else:
                    state = "BLK:" + n[2:]
                prio = f.get("priority", t.segs[-1].prio if t.segs else 0)
                if t.base_prio is None:
                    t.base_prio = prio
                if not t.prio_changes or t.prio_changes[-1][1] != prio:
                    t.prio_changes.append((ev.t, prio, ev.idx))
                prev = open_seg.get(k)
                if prev:
                    prev.t1 = ev.t
                    # a blocked thread that is "running" again on a CPU keeps its CPU set by THRUNNING
                seg = Seg(ev.t, ev.t, state, prio, ev.cpu, ev.idx)
                t.segs.append(seg)
                open_seg[k] = seg
                if state != "RUN" and self.cpu_cur.get(ev.cpu) == k:
                    self.cpu_cur.pop(ev.cpu, None)
            elif c == "PROCESS":
                if n == "PROCTHREAD_NAME" and "pid" in f:
                    self.th(f["pid"], f["tid"]).name = str(f.get("name", ""))
                elif n in ("PROCCREATE_NAME", "PROCCREATE") and "pid" in f and "name" in f:
                    self.procs[f["pid"]] = str(f["name"])
            elif c == "USREVENT":
                who = self.caller(ev)
                self.markers.append((ev.t, ev.idx, who, f.get("code", 0), f.get("text", "")))
                self.has_pf = True
                if f.get("code") == 1 and who:           # PF_EV_NAME
                    th = self.th(*who)
                    if not th.name:
                        th.name = f["text"]
            elif c == "KER_CALL":
                if n == "SYNC_MUTEX_LOCK":
                    who = self.caller(ev)
                    if who:
                        self.mutex_waits.append((ev.t, ev.idx, who, f.get("sync_p"), (f.get("owner", 0) & 0xffff) if isinstance(f.get("owner"), int) else None))
                elif n == "MSG_RECEIVEV":
                    who = self.caller(ev)
                    if who and "chid" in f:
                        self.recv_chan[who] = f["chid"]
                elif n == "CONNECT_ATTACH":
                    who = self.caller(ev)
                    if who:
                        self._pending_attach[who] = (f.get("pid"), f.get("chid"))
                elif n in ("MSG_SENDV", "MSG_SENDVNC", "MSG_SEND"):
                    who = self.caller(ev)
                    if who:
                        self._last_coid[who] = (f.get("coid", 0) & 0x3fffffff)
            elif c == "KER_EXIT":
                if n == "CONNECT_ATTACH":
                    who = self.caller(ev)
                    if who and who in self._pending_attach and isinstance(f.get("coid"), int):
                        self.coid_chan[(who[0], f["coid"] & 0x3fffffff)] = self._pending_attach.pop(who)
                elif n in ("MSG_RECEIVEV", "MSG_RECEIVEPULSEV") and "rcvid" in f:
                    who = self.caller(ev)
                    ch = self.recv_chan.get(who) if who else None
                    if who and ch is not None:
                        self.recv[(who[0], ch)].add(who)
            elif c == "COMM":
                if n == "SND_MESSAGE":
                    who = self.caller(ev)
                    if who:
                        self.sends[who].append((ev.t, ev.idx, f.get("rcvid"), f.get("pid"), self._last_coid.get(who)))
                elif n == "REC_MESSAGE":
                    who = self.caller(ev)
                    if who:
                        self.rec[f.get("rcvid")] = (who, ev.t, ev.idx)
                elif n == "REPLY_MESSAGE" and "pid" in f and "tid" in f:
                    self.replied[(f["pid"], f["tid"])] = ev.t
        for seg in open_seg.values():
            seg.t1 = self.t_end
        for t in self.threads.values():
            dur = {}
            for sg in t.segs:
                dur[sg.prio] = dur.get(sg.prio, 0.0) + (sg.t1 - sg.t0)
            if dur:
                t.base_prio = max(dur.items(), key=lambda kv: kv[1])[0]
        # fill zero-length segs
        for t in self.threads.values():
            t.segs = [s for s in t.segs if s.t1 > s.t0 or s.state == "RUN"]

    # ---------- queries ----------
    def state_at(self, key, t):
        th = self.threads.get(key)
        if not th:
            return None
        for s in th.segs:
            if s.t0 <= t < s.t1:
                return s
        return None

    def prio_at(self, key, t):
        s = self.state_at(key, t)
        return s.prio if s else None

    def interesting(self):
        """Threads worth drawing: not kernel idle/system noise, i.e. have a name from markers/names or non-trivial priority."""
        out = []
        for t in self.threads.values():
            if t.pid == 1:
                continue
            if t.segs and any(s.prio > 0 for s in t.segs):
                out.append(t)
        return out
