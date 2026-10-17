#!/usr/bin/env python3
"""Minimal OTLP/HTTP-JSON sink: appends every POST body to a JSONL file; GET / shows a raw-data panel."""
import json, time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 7811
OUT = "/tmp/claude-otel.jsonl"
CONSOLE_OUT = "/tmp/claude-otel-console.jsonl"
TAIL_MAX = 200  # records served to the panel
POLL_MS = 3000
PAGE_SIZE = 5
HIST_BINS = 20
HIST_DEFAULT = "cost_usd"

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>claude otel</title>
<style>
body{margin:0;background:#111;color:#ddd;font:13px/1.45 ui-monospace,monospace}
header{position:sticky;top:0;background:#181818;border-bottom:1px solid #2a2a2a;padding:10px 16px;display:flex;gap:12px;align-items:center}
h1{font-size:14px;margin:0;color:#eee;font-weight:600}
button{background:#222;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 10px;cursor:pointer;font:inherit}
button.on{background:#2d3b55;border-color:#46618f;color:#fff}
main{padding:12px 16px 48px}
details{background:#171717;border:1px solid #262626;border-radius:6px;margin-bottom:8px}
summary{padding:8px 12px;cursor:pointer;display:flex;gap:12px;align-items:baseline}
.t{color:#777}.k{padding:0 6px;border-radius:3px;font-size:11px}
.k.logs{background:#2c3a2a;color:#9c9}.k.metrics{background:#2a3140;color:#9bd}.k.other{background:#333;color:#aaa}
.n{color:#bbb;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
pre{margin:0;padding:10px 12px;border-top:1px solid #262626;overflow:auto;max-height:60vh;color:#ccc}
.s{color:#c9a96e}.num{color:#8fc0e0}.b{color:#d58}.key{color:#9ab}
.v{display:flex;flex-wrap:wrap;gap:4px 14px;padding:0 12px 8px 12px;color:#8fc0e0}.v:empty{display:none}.v i{color:#777;font-style:normal}
#hist{padding:12px 16px 4px;border-bottom:1px solid #2a2a2a}.hh{display:flex;gap:12px;align-items:center;margin-bottom:8px}
select{background:#222;color:#ddd;border:1px solid #333;border-radius:4px;padding:2px 6px;font:inherit}
#bars{display:flex;align-items:flex-end;gap:2px;height:120px}#bars div{flex:1;background:#46618f;min-height:1px;border-radius:2px 2px 0 0}
#bars div:hover{background:#6b8fd0}#axis{display:flex;justify-content:space-between;font-size:11px;margin-top:3px}
#more{display:block;margin:12px auto}
footer{position:fixed;bottom:0;left:0;right:0;background:#181818;border-top:1px solid #2a2a2a;padding:4px 16px;color:#777;font-size:12px}
</style></head><body>
<header><h1>claude otel</h1>
<button data-f="all" class="on">All</button><button data-f="logs">Logs</button><button data-f="metrics">Metrics</button>
<button id="pause">Pause</button></header>
<section id="hist"><div class="hh"><select id="hsel"></select><span id="hinfo" class="t"></span></div>
<div id="bars"></div><div id="axis" class="t"></div></section>
<main id="list"></main><button id="more">View more</button>
<footer id="status">loading…</footer>
<script>
const POLL=__POLL__,PAGE=__PAGE__,BINS=__BINS__;let hfield="__HDEF__";
let recs=[],filter="all",shown=PAGE,paused=false,open=new Set();
const report=(type,msg)=>fetch("/console",{method:"POST",body:JSON.stringify({type,msg,ts:Date.now()})}).catch(()=>{});
addEventListener("error",e=>report("error",e.message+" @"+e.lineno));
addEventListener("unhandledrejection",e=>report("rejection",String(e.reason)));
const kind=p=>p.includes("logs")?"logs":p.includes("metrics")?"metrics":"other";
const av=v=>v.stringValue??v.intValue??v.doubleValue??v.boolValue;
const SKIP_NUM=new Set(["event.sequence","cost_usd_micros"]);
function names(d){const s=new Set();
  for(const r of d.resourceLogs||[])for(const sl of r.scopeLogs||[])for(const l of sl.logRecords||[])s.add((l.body?.stringValue||"log").replace("claude_code.",""));
  for(const r of d.resourceMetrics||[])for(const sm of r.scopeMetrics||[])for(const m of sm.metrics||[])s.add(m.name.replace("claude_code.",""));
  return [...s].join(", ")||JSON.stringify(d).slice(0,80)}
function nums(d){const out=[];
  for(const r of d.resourceMetrics||[])for(const sm of r.scopeMetrics||[])for(const m of sm.metrics||[]){
    const k=Object.keys(m).find(x=>!["name","description","unit"].includes(x));
    for(const p of m[k]?.dataPoints||[]){const t=(p.attributes||[]).find(a=>a.key==="type");
      out.push([m.name.replace("claude_code.","")+(t?"·"+av(t.value):""),+(p.asDouble??p.asInt),m.unit||""])}}
  for(const r of d.resourceLogs||[])for(const sl of r.scopeLogs||[])for(const l of sl.logRecords||[])
    for(const a of l.attributes||[])if(("intValue" in a.value||"doubleValue" in a.value)&&!SKIP_NUM.has(a.key))out.push([a.key,+av(a.value),""]);
  return out}
const fmt=n=>Number.isInteger(n)?n.toLocaleString():n.toPrecision(4).replace(/\.?0+$/,"");
const esc=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
const hl=j=>esc(JSON.stringify(j,null,2)).replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(-?\d+\.?\d*(?:e[+-]?\d+)?)\b|\b(true|false|null)\b/g,
  (m,s,c,n,b)=>s?(c?`<span class="key">${s}</span>${c}`:`<span class="s">${s}</span>`):n?`<span class="num">${n}</span>`:`<span class="b">${b}</span>`);
function samples(){const out={};
  for(const r of recs)for(const rl of r.data.resourceLogs||[])for(const sl of rl.scopeLogs||[])for(const l of sl.logRecords||[]){
    if(l.body?.stringValue!=="claude_code.api_request")continue;
    for(const a of l.attributes||[])if(("intValue" in a.value||"doubleValue" in a.value)&&!SKIP_NUM.has(a.key))(out[a.key]??=[]).push(+av(a.value))}
  return out}
function renderHist(){const S=samples(),keys=Object.keys(S).sort(),sel=document.getElementById("hsel");
  if(sel.options.length!==keys.length)sel.innerHTML=keys.map(k=>`<option>${k}</option>`).join("");
  if(!keys.includes(hfield)&&keys.length)hfield=keys[0];sel.value=hfield;
  const v=S[hfield]||[],bars=document.getElementById("bars"),axis=document.getElementById("axis");
  if(!v.length){bars.innerHTML="";axis.innerHTML="";document.getElementById("hinfo").textContent="no api_request yet";return}
  const lo=Math.min(...v),hi=Math.max(...v),w=(hi-lo)/BINS||1,c=Array(BINS).fill(0);
  for(const x of v)c[Math.min(BINS-1,Math.floor((x-lo)/w))]++;const mx=Math.max(...c);
  bars.innerHTML=c.map((n,i)=>`<div style="height:${n/mx*100}%" title="${fmt(lo+i*w)} – ${fmt(lo+(i+1)*w)}: ${n}"></div>`).join("");
  axis.innerHTML=`<span>${fmt(lo)}</span><span>${fmt(hi)}</span>`;
  const sum=v.reduce((a,b)=>a+b,0);
  document.getElementById("hinfo").textContent=`n=${v.length} · mean ${fmt(sum/v.length)} · sum ${fmt(sum)}`}
function render(){renderHist();
  const v=recs.filter(r=>filter==="all"||kind(r.path)===filter);
  document.getElementById("list").innerHTML=v.slice(0,shown).map(r=>{const id=r.ts+r.path;
    return `<details data-id="${id}" ${open.has(id)?"open":""}><summary><span class="t">${new Date(r.ts*1000).toLocaleTimeString()}</span>
    <span class="k ${kind(r.path)}">${kind(r.path)}</span><span class="n">${esc(names(r.data))}</span></summary>
    <div class="v">${nums(r.data).map(([k,n,u])=>`<span><i>${esc(k)}</i> ${fmt(n)}${u&&u!=="1"?" "+esc(u):""}</span>`).join("")}</div>
    ${open.has(id)?`<pre>${hl(r.data)}</pre>`:""}</details>`}).join("")||'<p class="t">No data yet.</p>';
  document.getElementById("more").style.display=v.length>shown?"block":"none";
  document.getElementById("status").textContent=`${v.length} records · showing ${Math.min(shown,v.length)} · ${paused?"paused":"live, every "+POLL/1000+"s"} · /tmp/claude-otel.jsonl`;
}
document.getElementById("list").addEventListener("toggle",e=>{const id=e.target.dataset.id;
  e.target.open?open.add(id):open.delete(id);render()},true);
document.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{filter=b.dataset.f;shown=PAGE;
  document.querySelectorAll("[data-f]").forEach(x=>x.classList.toggle("on",x===b));render()});
document.getElementById("hsel").onchange=e=>{hfield=e.target.value;renderHist()};
document.getElementById("more").onclick=()=>{shown+=PAGE*4;render()};
document.getElementById("pause").onclick=e=>{paused=!paused;e.target.classList.toggle("on",paused);render()};
async function poll(){if(!paused){try{recs=(await (await fetch("/data")).json()).reverse();render()}catch(e){report("poll",String(e))}}
  setTimeout(poll,POLL)}
poll();
</script></body></html>""".replace("__POLL__", str(POLL_MS)).replace("__PAGE__", str(PAGE_SIZE)).replace("__BINS__", str(HIST_BINS)).replace("__HDEF__", HIST_DEFAULT)


class H(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/data":
            try:
                with open(OUT) as f:
                    lines = deque(f, TAIL_MAX)
            except FileNotFoundError:
                lines = []
            recs = []
            for l in lines:
                try:
                    recs.append(json.loads(l))
                except Exception:
                    pass
            self._send(200, "application/json", json.dumps(recs).encode())
        else:
            self._send(200, "text/html; charset=utf-8", PAGE.encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body.decode("utf-8", "replace")}
        out = CONSOLE_OUT if self.path == "/console" else OUT
        with open(out, "a") as f:
            f.write(json.dumps({"ts": time.time(), "path": self.path, "data": data}) + "\n")
        self._send(200, "application/json", b"{}")

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
