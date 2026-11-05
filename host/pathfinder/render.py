"""Self-contained report: one HTML file (inline SVG + JS, no network, no external libraries), plus Markdown and JSON."""
import json
from .detect import focus_pids

STATES = ["RUN", "READY", "BLK:MUTEX", "BLK:SEM", "BLK:CONDVAR", "BLK:SEND", "BLK:RECEIVE", "BLK:REPLY", "BLK:SLEEP", "BLK:OTHER"]


def _sidx(s):
    return STATES.index(s) if s in STATES else STATES.index("BLK:OTHER")


def build_data(model, findings, title=""):
    hdr = model.hdr
    focus = focus_pids(model)
    inv_keys = {k for f in findings for k in f.threads}
    lanes = []
    for k, th in model.threads.items():
        if th.pid == 1 or not th.segs:
            continue
        if focus is not None and th.pid not in focus and k not in inv_keys:
            continue
        if focus is None and not any(s.prio > 0 and s.state == "RUN" for s in th.segs):
            continue
        lanes.append(th)
    lanes.sort(key=lambda t: (-(t.base_prio or 0), t.tid))
    lanes = lanes[:24]
    ids = {t.key: i for i, t in enumerate(lanes)}
    if model.has_pf:
        ts = [m[0] for m in model.markers]
        w0, w1 = max(0.0, min(ts) - 5000), min(model.t_end, max(ts) + 20000)
    else:
        w0, w1 = 0.0, model.t_end
    out_lanes = []
    for t in lanes:
        segs = []
        for s in t.segs:
            if s.t1 < w0 or s.t0 > w1:
                continue
            segs.append([round(max(s.t0, w0) / 1000, 3), round(min(s.t1, w1) / 1000, 3), _sidx(s.state), s.prio, s.cpu, s.ev0])
        out_lanes.append({"id": ids[t.key], "label": t.label, "pid": t.pid, "tid": t.tid, "base": t.base_prio, "segs": segs})
    marks = []
    for (t, idx, who, code, text) in model.markers:
        if code in (2, 4) and who in ids:
            marks.append({"t": round(t / 1000, 3), "lane": ids[who], "code": code, "text": text, "idx": idx})
    evid = {}
    need = set()
    for f in findings:
        need.update(f.evidence)
    for i in need:
        e = model.byidx.get(i)
        if e:
            evid[i] = {"t": round(e.t / 1000, 3), "raw": e.raw[:230]}
    fl = []
    for f in findings:
        fl.append({"id": f.id, "kind": f.kind, "sev": f.severity, "title": f.title, "t0": round(f.t0 / 1000, 3), "t1": round(f.t1 / 1000, 3),
                   "lanes": [ids[k] for k in f.threads if k in ids], "root": f.root_cause, "fix": f.fix, "evidence": f.evidence,
                   "inst": [[round(i["t0"] / 1000, 3), round(i["t1"] / 1000, 3)] for i in f.instances], "causes": f.cause_of,
                   "waiter": ids.get(f.data.get("waiter")), "owner": ids.get(f.data.get("owner")), "llm": getattr(f, "llm_text", "")})
    meta = {"title": title, "sys": "%s %s %s" % (hdr.get("TRACE_SYSNAME", ""), hdr.get("TRACE_SYS_RELEASE", ""), hdr.get("TRACE_MACHINE", "")),
            "node": hdr.get("TRACE_NODENAME", ""), "file": hdr.get("TRACE_FILE_NAME", ""), "cpus": hdr.get("_cpus"), "events": len(model.events),
            "args": hdr.get("TRACE_TRACELOGGER_ARGS", ""), "w0": round(w0 / 1000, 3), "w1": round(w1 / 1000, 3)}
    return {"meta": meta, "states": STATES, "lanes": out_lanes, "marks": marks, "findings": fl, "evidence": evid}


def to_html(data):
    js = json.dumps(data).replace("</", "<\\/")
    return HTML.replace("__DATA__", js)


def to_markdown(model, findings, data):
    m = data["meta"]
    L = ["# Pathfinder report: %s" % (m["title"] or m["file"]), "",
         "Trace: `%s` | %s on `%s` | %d CPUs | %d events | tracelogger: `%s`" % (m["file"], m["sys"], m["node"], m["cpus"], m["events"], m["args"]), ""]
    if not findings:
        L.append("No findings.")
    for f in findings:
        L += ["## %s [%s] %s" % (f.id, f.severity.upper(), f.title), "",
              "Window: %.1f - %.1f ms. Evidence events: %s." % (f.t0 / 1000, f.t1 / 1000, ", ".join("#%d" % i for i in f.evidence)), "",
              "**Root cause.** " + f.root_cause, "", "**Fix.** " + f.fix, ""]
        if f.cause_of:
            L.append("Leads to: %s." % ", ".join(f.cause_of))
            L.append("")
        if getattr(f, "llm_text", ""):
            L += ["**LLM narrative (every claim cites trace events).** " + f.llm_text, ""]
    return "\n".join(L)


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pathfinder trace report</title>
<style>
:root{--bg:#10141a;--panel:#171d26;--fg:#e6ebf2;--mut:#8a97a8;--line:#2a3340;--run:#2e9e5b;--ready:#e0a030;--mutex:#d8453b;--sem:#e0643b;--cv:#8a6bd8;--send:#3b8fd8;--recv:#2b6a9e;--reply:#3bb0d8;--sleep:#3a4658;--other:#566272;--crit:#ff5a4f;--warn:#e0a030;--info:#4aa3e8}
@media (prefers-color-scheme: light){:root{--bg:#f4f6f9;--panel:#fff;--fg:#1b2430;--mut:#5a6778;--line:#d6dce5;--sleep:#c4ccd8;--other:#aab4c2}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}h1{font-size:17px;margin:0 0 2px}.sub{color:var(--mut);font-size:12px}
main{display:grid;grid-template-columns:minmax(280px,360px) 1fr;gap:12px;padding:12px 16px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.f{border-left:4px solid var(--info);padding:6px 8px;margin:6px 0;cursor:pointer;border-radius:4px;background:rgba(127,127,127,.07)}
.f.critical{border-color:var(--crit)}.f.warning{border-color:var(--warn)}.f.sel{outline:2px solid var(--info)}
.f b{font-size:12px;color:var(--mut)}.tag{display:inline-block;font-size:11px;padding:0 6px;border-radius:9px;margin-right:6px;color:#fff;background:var(--info)}
.tag.critical{background:var(--crit)}.tag.warning{background:var(--warn)}
#detail h3{margin:.2em 0}#detail p{margin:.4em 0}.ev{font:11px/1.35 ui-monospace,Menlo,monospace;color:var(--mut);cursor:pointer;word-break:break-all}.ev:hover{color:var(--fg)}
svg{width:100%;display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px;cursor:grab;user-select:none}
.legend span{display:inline-block;margin-right:10px;font-size:12px}.legend i{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px;vertical-align:-1px}
#tip{position:fixed;pointer-events:none;background:#000c;color:#fff;font-size:12px;padding:4px 8px;border-radius:4px;display:none;white-space:pre}
button{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 9px;cursor:pointer}
</style></head><body>
<header><h1 id="ttl">Pathfinder trace report</h1><div class="sub" id="sub"></div></header>
<main>
<div><div class="panel"><b>Findings</b><div id="list"></div></div><div class="panel" id="detail" style="margin-top:12px"><span class="sub">Select a finding. Drag to pan, wheel to zoom, double-click to reset.</span></div></div>
<div><div class="legend panel" id="legend" style="margin-bottom:8px"></div><svg id="tl"></svg>
<div style="margin-top:6px"><button id="rst">Reset view</button> <span class="sub" id="rng"></span></div></div>
</main><div id="tip"></div>
<script>
const D=__DATA__;
const COL=["--run","--ready","--mutex","--sem","--cv","--send","--recv","--reply","--sleep","--other"];
const NAMES=["running","ready (waiting for CPU)","blocked: mutex","blocked: semaphore","blocked: condvar","blocked: send","blocked: receive","blocked: reply","sleeping","blocked: other"];
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const svg=document.getElementById('tl'),NS='http://www.w3.org/2000/svg';
const G=72,TOP=26,LH=44,PAD=12;
let W=1000,v0=D.meta.w0,v1=D.meta.w1,sel=null;
document.getElementById('ttl').textContent=D.meta.title||'Pathfinder trace report';
document.getElementById('sub').textContent=D.meta.file+' | '+D.meta.sys+' | '+D.meta.cpus+' CPUs | '+D.meta.events+' kernel events | '+D.meta.args;
document.getElementById('legend').innerHTML=COL.map((c,i)=>'<span><i style="background:var('+c+')"></i>'+NAMES[i]+'</span>').join('')+'<span>&#9660; watchdog reset / deadlock noticed by the app</span><span>| job begin/end</span>';
function el(n,a,p){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);(p||svg).appendChild(e);return e}
const X=t=>G+(t-v0)/(v1-v0)*(W-G-PAD);const T=x=>v0+(x-G)/(W-G-PAD)*(v1-v0);
function draw(){
 W=svg.clientWidth||1000;const H=TOP+D.lanes.length*LH+30;svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('height',H);svg.innerHTML='';
 // time axis
 const span=v1-v0;let step=1;const nice=[1,2,5,10,20,50,100,200,500,1000,2000,5000];for(const s of nice){if(span/s<=14){step=s;break}}
 for(let t=Math.ceil(v0/step)*step;t<=v1;t+=step){el('line',{x1:X(t),x2:X(t),y1:TOP-6,y2:TOP+D.lanes.length*LH,stroke:css('--line'),'stroke-width':1});
  const tx=el('text',{x:X(t)+2,y:TOP-10,fill:css('--mut'),'font-size':10});tx.textContent=(t-D.meta.w0).toFixed(step<1?1:0)+' ms'}
 const f=sel!=null?D.findings.find(x=>x.id===sel):null;
 D.lanes.forEach((L,i)=>{const y=TOP+i*LH;
  const lb=el('text',{x:4,y:y+LH/2-2,fill:css('--fg'),'font-size':12,'font-weight':600});lb.textContent=L.label;
  const lp=el('text',{x:4,y:y+LH/2+11,fill:css('--mut'),'font-size':10});lp.textContent='prio '+L.base+' (t'+L.tid+')';
  el('rect',{x:G,y:y+2,width:W-G-PAD,height:LH-4,fill:'none',stroke:css('--line')});
  let lastP=null,pts=[];
  L.segs.forEach(s=>{if(s[1]<v0||s[0]>v1)return;const x0=Math.max(G,X(s[0])),x1=Math.min(W-PAD,X(s[1]));if(x1-x0<0.4)return;
   const r=el('rect',{x:x0,y:y+12,width:Math.max(0.6,x1-x0),height:LH-18,fill:css(COL[s[2]]),opacity:s[2]===8?.55:1});
   r.addEventListener('mousemove',e=>tip(e,L.label+'\n'+NAMES[s[2]]+'\npriority '+s[3]+'  cpu '+s[4]+'\n'+(s[0]-D.meta.w0).toFixed(2)+' - '+(s[1]-D.meta.w0).toFixed(2)+' ms ('+(s[1]-s[0]).toFixed(2)+' ms)\nevent #'+s[5]));
   r.addEventListener('mouseleave',()=>tip());
   pts.push([x0,s[3]],[x1,s[3]]);});
  // priority step line in the strip above the bars
  if(pts.length){let d='',mx=Math.max(...D.lanes.map(l=>l.base||0),1);pts.forEach((p,k)=>{const yy=y+4+ (1-Math.min(1,p[1]/Math.max(mx,p[1])))*7;d+=(k?'L':'M')+p[0].toFixed(1)+' '+yy.toFixed(1)});
   el('path',{d:d,fill:'none',stroke:css('--info'),'stroke-width':1.2});}
 });
 D.marks.forEach(m=>{if(m.t<v0||m.t>v1)return;const y=TOP+m.lane*LH;
  if(m.code===4&&/WATCHDOG|DEADLOCK/i.test(m.text)){const p=el('path',{d:'M'+(X(m.t)-5)+' '+(y+1)+'L'+(X(m.t)+5)+' '+(y+1)+'L'+X(m.t)+' '+(y+11)+'Z',fill:css('--crit')});p.addEventListener('mousemove',e=>tip(e,m.text));p.addEventListener('mouseleave',()=>tip())}
  else{el('line',{x1:X(m.t),x2:X(m.t),y1:y+3,y2:y+LH-3,stroke:css('--fg'),'stroke-width':.8,opacity:.5})}});
 // finding overlay
 if(f){f.inst.forEach(w=>{if(w[1]<v0||w[0]>v1)return;f.lanes.forEach(li=>{const y=TOP+li*LH;el('rect',{x:X(w[0]),y:y+2,width:Math.max(1,X(w[1])-X(w[0])),height:LH-4,fill:css('--crit'),opacity:.18,'pointer-events':'none'})})});
  if(f.waiter!=null&&f.owner!=null){const x=X((f.t0+f.t1)/2),a=TOP+f.waiter*LH+LH/2,b=TOP+f.owner*LH+LH/2;el('line',{x1:x,x2:x,y1:a,y2:b,stroke:css('--fg'),'stroke-width':2,'stroke-dasharray':'4 3'});
   const t=el('text',{x:x+5,y:(a+b)/2,fill:css('--fg'),'font-size':11});t.textContent='waits for';}}
 document.getElementById('rng').textContent='view '+(v0-D.meta.w0).toFixed(1)+' - '+(v1-D.meta.w0).toFixed(1)+' ms';
}
const tipEl=document.getElementById('tip');function tip(e,t){if(!t){tipEl.style.display='none';return}tipEl.textContent=t;tipEl.style.display='block';tipEl.style.left=(e.clientX+12)+'px';tipEl.style.top=(e.clientY+12)+'px'}
function list(){const L=document.getElementById('list');L.innerHTML='';if(!D.findings.length){L.innerHTML='<p class="sub">No findings: nothing suspicious in this trace.</p>';return}
 D.findings.forEach(f=>{const d=document.createElement('div');d.className='f '+f.sev+(f.id===sel?' sel':'');d.innerHTML='<b><span class="tag '+f.sev+'">'+f.sev+'</span>'+f.id+' '+f.kind.replace('_',' ')+'</b><div>'+f.title+'</div>';d.onclick=()=>pick(f.id);L.appendChild(d)})}
function pick(id){sel=id;const f=D.findings.find(x=>x.id===id);list();
 const pad=Math.max(20,(f.t1-f.t0)*0.8);v0=Math.max(D.meta.w0,f.t0-pad);v1=Math.min(D.meta.w1,f.t1+pad);
 const ev=f.evidence.map(i=>{const e=D.evidence[i];return e?'<div class="ev" data-t="'+e.t+'">#'+i+'  '+e.raw.replace(/</g,'&lt;')+'</div>':''}).join('');
 document.getElementById('detail').innerHTML='<h3>'+f.id+' '+f.title+'</h3><p><b>Root cause.</b> '+f.root+'</p><p><b>Fix.</b> '+f.fix+'</p>'+(f.causes.length?'<p><b>Leads to:</b> '+f.causes.join(', ')+'</p>':'')+(f.llm?'<p><b>LLM narrative (each claim cites events):</b> '+f.llm+'</p>':'')+'<p class="sub">Evidence (click to jump):</p>'+ev;
 document.querySelectorAll('.ev').forEach(e=>e.onclick=()=>{const t=+e.dataset.t,w=(v1-v0)/2;v0=Math.max(D.meta.w0,t-w/2);v1=v0+w;draw()});draw()}
svg.addEventListener('wheel',e=>{e.preventDefault();const r=svg.getBoundingClientRect(),x=(e.clientX-r.left)*(W/r.width),t=T(x),k=e.deltaY<0?.8:1.25;
 v0=Math.max(D.meta.w0,t-(t-v0)*k);v1=Math.min(D.meta.w1,t+(v1-t)*k);if(v1-v0<0.5){v1=v0+0.5}draw()},{passive:false});
let drag=null;svg.addEventListener('mousedown',e=>{drag={x:e.clientX,v0,v1}});window.addEventListener('mouseup',()=>drag=null);
window.addEventListener('mousemove',e=>{if(!drag)return;const r=svg.getBoundingClientRect(),dt=(e.clientX-drag.x)*(drag.v1-drag.v0)/(r.width-G-PAD);let a=drag.v0-dt,b=drag.v1-dt;if(a<D.meta.w0){b+=D.meta.w0-a;a=D.meta.w0}if(b>D.meta.w1){a-=b-D.meta.w1;b=D.meta.w1}v0=a;v1=b;draw()});
const reset=()=>{v0=D.meta.w0;v1=D.meta.w1;draw()};svg.addEventListener('dblclick',reset);document.getElementById('rst').onclick=reset;window.addEventListener('resize',draw);
list();draw();if(D.findings.length)pick(D.findings[0].id);
</script></body></html>'''
