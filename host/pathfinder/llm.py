"""Optional LLM narrative layer (off by default: `pathfinder analyze --llm`).

Safety contract
  * Only the structured findings (numbers + the few cited event lines) are sent, never the trace file.
  * The model must answer with claims, each citing event ids it was given. Claims citing unknown ids, or with no id, are dropped;
    if nothing valid remains the deterministic explanation is kept untouched.
  * The key is read from $ANTHROPIC_API_KEY or from the file named by $PF_ENV_FILE (KEY=VALUE lines); it is never printed or logged.
"""
import json, os, re, urllib.request, urllib.error

MODEL = os.environ.get("PF_LLM_MODEL", "claude-sonnet-5-5")
URL = "https://api.anthropic.com/v1/messages"


def _key():
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k
    path = os.environ.get("PF_ENV_FILE")
    if path and os.path.exists(path):
        for line in open(path):
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _facts(model, f):
    ev = {}
    for i in f.evidence:
        e = model.byidx.get(i)
        if e:
            ev[str(i)] = e.raw[:200]
    d = {k: (v if isinstance(v, (int, float, str, bool)) else str(v)) for k, v in f.data.items()}
    return {"id": f.id, "kind": f.kind, "severity": f.severity, "title": f.title, "window_ms": [round(f.t0 / 1000, 1), round(f.t1 / 1000, 1)],
            "data": d, "events": ev, "deterministic_root_cause": f.root_cause, "deterministic_fix": f.fix}


PROMPT = """You are explaining a real-time bug found in a QNX Neutrino 8.0 kernel trace to an embedded engineer.
For each finding below write at most 4 short claims in plain language. Every claim MUST cite at least one event id from that finding's
"events" object (use only those ids) and must only restate facts present in the finding data or event text; do not invent numbers, names or causes.
Answer with JSON only: {"narratives":[{"finding":"F1","claims":[{"text":"...","events":[123,124]}]}]}

FINDINGS:
%s"""


def enrich(model, findings, timeout=60):
    key = _key()
    if not key:
        print("pathfinder: --llm requested but no ANTHROPIC_API_KEY / PF_ENV_FILE; keeping deterministic text")
        return
    facts = [_facts(model, f) for f in findings if f.severity != "info"]
    if not facts:
        return
    body = json.dumps({"model": MODEL, "max_tokens": 1500, "messages": [{"role": "user", "content": PROMPT % json.dumps(facts, indent=1)}]}).encode()
    req = urllib.request.Request(URL, body, {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
        text = "".join(b.get("text", "") for b in resp.get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0))
    except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
        print("pathfinder: LLM layer skipped (%s)" % type(e).__name__)
        return
    by = {f.id: f for f in findings}
    kept = dropped = 0
    for nar in out.get("narratives", []):
        f = by.get(nar.get("finding"))
        if not f:
            continue
        allowed = {int(i) for i in f.evidence}
        parts = []
        for c in nar.get("claims", []):
            ids = [i for i in c.get("events", []) if isinstance(i, int)]
            if not ids or any(i not in allowed for i in ids) or not c.get("text"):
                dropped += 1
                continue
            parts.append("%s [%s]" % (c["text"].strip(), ", ".join("#%d" % i for i in ids)))
            kept += 1
        if parts:
            f.llm_text = " ".join(parts)
    print("pathfinder: LLM narrative kept %d claims, dropped %d uncited/invalid claims" % (kept, dropped))
