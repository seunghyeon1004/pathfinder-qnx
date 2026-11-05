"""Run against real traces recorded on QNX 8.0 (examples/traces/*.txt.gz). `python3 -m unittest discover host/tests`"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from pathfinder import parse, model, detect, explain  # noqa: E402

TR = os.path.join(HERE, "..", "..", "examples", "traces")


def run(name):
    hdr, ev = parse.load(os.path.join(TR, name + ".txt.gz"))
    m = model.Model(hdr, ev)
    f = detect.analyze(m)
    explain.explain(m, f)
    return hdr, m, f


def kinds(f, sev=None):
    return {x.kind for x in f if sev is None or x.severity == sev}


class RealTraces(unittest.TestCase):
    def test_header_is_qnx8(self):
        hdr, m, f = run("mars_none")
        self.assertEqual(hdr["TRACE_SYSNAME"], "QNX")
        self.assertTrue(hdr["TRACE_SYS_RELEASE"].startswith("8.0"))

    def test_mars_none_priority_inversion_chain(self):
        _, m, f = run("mars_none")
        inv = [x for x in f if x.kind == "priority_inversion"]
        self.assertEqual(len(inv), 1)
        d = inv[0].data
        names = lambda k: m.threads[k].label
        self.assertEqual((names(d["waiter"]), names(d["owner"]), names(d["interferer"])), ("bus_mgr", "meteo", "comms"))
        self.assertEqual(d["owner_prio_during_block"], 10)        # never boosted
        self.assertGreater(d["worst_starved_ms"], 100)
        self.assertIn("deadline_miss", kinds(f))
        self.assertIn("watchdog_reset", kinds(f))
        # causal chain: inversion -> deadline_miss -> watchdog
        ids = {x.kind: x for x in f}
        self.assertIn(ids["deadline_miss"].id, ids["priority_inversion"].cause_of)
        self.assertIn(ids["watchdog_reset"].id, ids["deadline_miss"].cause_of)

    def test_evidence_events_exist_and_are_relevant(self):
        _, m, f = run("mars_none")
        for x in f:
            self.assertTrue(x.evidence, x.id)
            for i in x.evidence:
                self.assertIn(i, m.byidx)

    def test_mars_sem_detected_through_markers(self):
        _, m, f = run("mars_sem")
        inv = [x for x in f if x.kind == "priority_inversion"]
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0].data["lock_kind"], "SEM")

    def test_mars_inherit_is_clean_and_shows_boost(self):
        _, m, f = run("mars_inherit")
        self.assertFalse(kinds(f, "critical"))
        boost = [x for x in f if x.kind == "priority_inheritance"]
        self.assertEqual(len(boost), 1)
        self.assertEqual(boost[0].data["base_prio"], 10)
        self.assertEqual(boost[0].data["boosted_prio"], 30)

    def test_mars_protect_clean(self):
        _, m, f = run("mars_protect")
        self.assertFalse(kinds(f, "critical"))

    def test_ipc_deadlock_cycle(self):
        _, m, f = run("ipc_deadlock_bug")
        dl = [x for x in f if x.kind == "ipc_deadlock"]
        self.assertEqual(len(dl), 1)
        cyc = {m.threads[k].label for k in dl[0].data["cycle"]}
        self.assertEqual(cyc, {"ping_srv", "pong_srv"})
        self.assertGreater(dl[0].data["blocked_ms"], 1000)
        self.assertEqual({m.threads[k].label for k in dl[0].data["victims"]}, {"client1", "client2"})

    def test_ipc_fix_clean(self):
        _, m, f = run("ipc_deadlock_fix")
        self.assertFalse(kinds(f, "critical"))

    def test_deadline_bug_is_long_critical_section_not_inversion(self):
        _, m, f = run("deadline_bug")
        self.assertIn("deadline_miss", kinds(f))
        self.assertNotIn("priority_inversion", kinds(f))
        self.assertTrue(any(x.kind == "priority_inheritance" and x.cause_of for x in f))

    def test_deadline_fix_clean(self):
        _, m, f = run("deadline_fix")
        self.assertFalse(kinds(f, "critical"))

    def test_starve_bug_and_fix(self):
        _, m, f = run("starve_bug")
        self.assertIn("deadline_miss", kinds(f))
        st = [x for x in f if x.kind == "starvation"]
        self.assertTrue(st and st[0].severity == "critical")
        _, m, f = run("starve_fix")
        self.assertFalse(kinds(f, "critical"))


class Parser(unittest.TestCase):
    def test_user_text_decode(self):
        f = {"d0": 0x6e69616d, "d1": 0}
        self.assertEqual(parse.user_text(f), "main")
        f = {"d0": 0x63746177, "d1": 0x676f6468, "d2": 0}      # exactly 8 chars, STR: missing in traceprinter output
        self.assertEqual(parse.user_text(f), "watchdog")


if __name__ == "__main__":
    unittest.main()
