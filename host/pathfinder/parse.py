"""Parse `traceprinter` text output (QNX SDP 8.0) into typed events.

Only the text format documented for traceprinter is used, so the analyzer needs nothing from the SDP at analysis time.
"""
import re
from dataclasses import dataclass, field

LINE = re.compile(r'^t:0x([0-9a-fA-F]+)\s+CPU:(\d+)\s+(\S+)\s*:(\S+)\s*(.*)$')
KV = re.compile(r'([A-Za-z_][\w.\[\]>-]*):("(?:[^"\\]|\\.)*"|[^\s,]+)')
HDR = re.compile(r'^\s*(TRACE_[A-Z_]+)::\s*(.*)$')


@dataclass
class Event:
    idx: int                 # 1-based position in the trace (this is the "event id" cited in findings)
    cyc: int                 # absolute cycle counter
    t: float = 0.0           # microseconds since first event
    cpu: int = 0
    cls: str = ""            # THREAD, KER_CALL, COMM, USREVENT, ...
    name: str = ""           # THRUNNING, SYNC_MUTEX_LOCK, ...
    raw: str = ""
    f: dict = field(default_factory=dict)

    @property
    def pid(self): return self.f.get("pid")

    @property
    def tid(self): return self.f.get("tid")

    @property
    def prio(self): return self.f.get("priority")

    def ms(self):
        return self.t / 1000.0


def _val(v):
    if v.startswith('"'):
        return v[1:-1]
    try:
        return int(v, 0)
    except ValueError:
        return v


def user_text(f):
    """Decode a user-event string from d0..dN words (little-endian), independent of the STR: rendering."""
    out = bytearray()
    for i in range(0, 12):
        w = f.get("d%d" % i)
        if not isinstance(w, int):
            break
        out += int(w & 0xffffffff).to_bytes(4, "little")
    s = out.split(b"\0", 1)[0].decode("latin-1")
    return s or (f.get("STR") or "")


def parse_text(text):
    """-> (header dict, [Event]). Events are numbered from 1 in file order."""
    hdr, events = {}, []
    in_events = False
    for line in text.splitlines():
        if not in_events:
            m = HDR.match(line)
            if m:
                hdr[m.group(1)] = m.group(2).strip()
            if "KERNEL EVENTS" in line:
                in_events = True
            continue
        m = LINE.match(line)
        if not m:
            continue
        cyc = int(m.group(1), 16)
        rest = m.group(5)
        name = m.group(4).split("/")[0]
        f = {k: _val(v) for k, v in KV.findall(rest)}
        ev = Event(idx=len(events) + 1, cyc=cyc, cpu=int(m.group(2)), cls=m.group(3), name=name, raw=line.strip(), f=f)
        if ev.cls == "USREVENT":
            code = m.group(4).split(":")[1] if ":" in m.group(4) else "0"
            ev.f["code"] = int(code) if code.isdigit() else 0
            ev.f["text"] = user_text(f)
        events.append(ev)
    cps = float(hdr.get("TRACE_CYCLES_PER_SEC", "1e9") or 1e9)
    hdr["_cps"] = cps
    hdr["_cpus"] = int(hdr.get("TRACE_CPU_NUM", "1") or 1)
    if events:
        c0 = events[0].cyc
        # the cycle counter is per-CPU-buffer ordered by the logger; keep file order, rebase to the minimum
        c0 = min(e.cyc for e in events if e.cyc)
        for e in events:
            e.t = (e.cyc - c0) * 1e6 / cps
    return hdr, events


def load(path):
    if path.endswith(".gz"):
        import gzip
        with gzip.open(path, "rt", errors="replace") as fh:
            return parse_text(fh.read())
    with open(path, "r", errors="replace") as fh:
        return parse_text(fh.read())
