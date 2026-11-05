"""pathfinder analyze <trace.kev|trace.txt> [--out DIR] [--llm] ; pathfinder compare A B"""
import argparse, os, subprocess, sys, shutil, json
from . import parse, model as M, detect, explain, render


def _to_text(path):
    if path.endswith(".txt") or path.endswith(".txt.gz"):
        return path
    # .kev -> run the SDP traceprinter (PATH) or the helper script (Docker env)
    out = os.path.splitext(path)[0] + ".traceprinter.txt"
    if shutil.which("traceprinter"):
        with open(out, "w") as fh:
            subprocess.check_call(["traceprinter", "-n", "-f", path], stdout=fh)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(here, "..", "..", "scripts", "traceprinter.sh")
        subprocess.check_call([script, path, out])
    return out


def run(path, outdir=None, title=None, cfg=None, llm=False, quiet=False):
    txt = _to_text(path)
    hdr, ev = parse.load(txt)
    model = M.Model(hdr, ev)
    findings = detect.analyze(model, cfg)
    explain.explain(model, findings)
    if llm:
        from . import llm as L
        L.enrich(model, findings)
    data = render.build_data(model, findings, title or os.path.basename(path))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        base = os.path.basename(path)
        for ext in (".txt.gz", ".kev", ".txt"):
            if base.endswith(ext):
                base = base[:-len(ext)]
                break
        base = base.replace(".traceprinter", "")
        with open(os.path.join(outdir, base + ".html"), "w") as fh:
            fh.write(render.to_html(data))
        with open(os.path.join(outdir, base + ".md"), "w") as fh:
            fh.write(render.to_markdown(model, findings, data))
        with open(os.path.join(outdir, base + ".json"), "w") as fh:
            json.dump({"meta": data["meta"], "findings": [dict(id=f.id, kind=f.kind, severity=f.severity, title=f.title, t0_ms=f.t0 / 1000, t1_ms=f.t1 / 1000,
                       evidence=f.evidence, root_cause=f.root_cause, fix=f.fix, causes=f.cause_of) for f in findings]}, fh, indent=1)
    return model, findings


def summary(findings):
    return {k: sum(1 for f in findings if f.kind == k) for k in sorted({f.kind for f in findings})}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pathfinder", description="Real-time trace doctor for QNX 8.0")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyze one trace")
    a.add_argument("trace")
    a.add_argument("--out", default="report")
    a.add_argument("--title")
    a.add_argument("--llm", action="store_true", help="add an LLM narrative (needs ANTHROPIC_API_KEY); claims must cite event ids")
    a.add_argument("--min-block-ms", type=float, default=5.0)
    a.add_argument("--min-inversion-ms", type=float, default=5.0)
    c = sub.add_parser("compare", help="analyze two traces (e.g. bug vs fix) and print a table")
    c.add_argument("before"); c.add_argument("after"); c.add_argument("--out", default="report")
    ns = ap.parse_args(argv)
    cfg = detect.Config()
    if ns.cmd == "analyze":
        cfg.min_block_ms, cfg.min_inversion_ms = ns.min_block_ms, ns.min_inversion_ms
        model, findings = run(ns.trace, ns.out, ns.title, cfg, ns.llm)
        print("%s: %d events, %d findings" % (ns.trace, len(model.events), len(findings)))
        for f in findings:
            print(" %s [%s] %s" % (f.id, f.severity, f.title))
        print("report: %s/*.html" % ns.out)
        sys.exit(1 if any(f.severity == "critical" for f in findings) else 0)
    elif ns.cmd == "compare":
        rows = []
        for p in (ns.before, ns.after):
            m, f = run(p, ns.out, None, cfg)
            rows.append((p, f))
        print("%-34s %-8s %s" % ("trace", "critical", "findings"))
        for p, f in rows:
            print("%-34s %-8d %s" % (os.path.basename(p), sum(1 for x in f if x.severity == "critical"), ", ".join("%s" % x.kind for x in f) or "-"))


if __name__ == "__main__":
    main()
