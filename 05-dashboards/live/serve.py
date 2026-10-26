#!/usr/bin/env python3
"""Single-user live dashboard: / = page, /data.json = last WINDOW_H hours of Claude Code api_request totals from the collector's file sink, /session.json?id= = one session's timeline from its transcript, /api/<tool>?args = live.py orchestrator tools (JSON), /api/orch_ux = <data dir>/orch_ux.json, POST /console = browser errors."""
import importlib.util, json, os, re, urllib.request
from urllib.parse import parse_qs, urlparse
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", int(os.environ.get("OTM_LIVE_PORT", 7845))  # env override for test servers
DATA = Path(os.environ.get("OTM_DATA_DIR", "~/.local/share/opentokenmini")).expanduser() / "otel"
LOG = "/tmp/otm-dashboards-console.jsonl"
MAX_EVENT = 8192  # bytes accepted per console event
TRANSCRIPTS = Path("~/.claude/projects").expanduser()  # local Claude Code transcripts, only read for session titles
WINDOW_H = 24  # timeline: last N hours, rolling, across day files
HERE = str(Path(__file__).parent)
EXCERPT = 160  # chars of each user prompt sent to the session timeline tooltip
D1 = "http://127.0.0.1:6975/ask"  # local decision model; classifies each prompt's edits into a column
ORCH_UX = DATA.parent / "orch_ux.json"  # orchestrator UX analysis, written by a separate analyzer
CATEGORIES = DATA.parent / "turn-categories.jsonl"  # cache: one line per classified prompt {uuid, cat, p}
CATS = [["Runtime", "changes code that runs: backend, scripts, server logic, data processing, algorithms"],
        ["UI", "changes what the user sees: HTML, CSS, front-end JS, layout, colors, charts"],
        ["Infra", "services, ports, processes, deploys, configs, environment, restarting servers"],
        ["Docs", "writes or edits README, AGENTS.md, markdown notes, comments"]]
WRITES = re.compile(r"sed -i|cat >|tee |>\s*(?!/tmp|/dev)[~/\w.-]+\.\w+|open\([^)]*['\"][wa]['\"]|\.write_text\(|\bmv |\bcp ")  # bash commands that write files
PLAN = [["Planning", "designing, investigating, analyzing data, proposing or comparing approaches, deciding what to build"],
        ["None", "trivial or mechanical: small talk, git push, compacting, checking a status, answering a quick fact"]]  # turns without edits
ACT_CHARS = 160  # chars of each action/reply of a turn without edits sent to d1
EDIT_CHARS = 300  # chars of each edit sent to d1
STATE_CHARS = 1500  # chars of prompt + edits sent to d1
REPO = next(p for p in Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
LIVE_PY = REPO / "06-optional" / "mcp-server" / "live.py"  # /api/<tool>: same functions as the otm-live MCP server
PRICE = {"input": 1, "read": 0.1, "write_5m": 1.25, "write_1h": 2, "output": 5}  # relative to base input price, same ratios for all Claude models
SKIP_PROMPTS = ("<system-reminder>", "<local-command", "<task-notification>")  # injected, not typed by the user


def records(day):
    p = DATA / f"logs-{day}.jsonl"
    if not p.exists():
        return
    for line in open(p):
        for rl in json.loads(line)["data"].get("resourceLogs", []):
            for sl in rl.get("scopeLogs", []):
                for lr in sl.get("logRecords", []):
                    yield {a["key"]: next(iter(a["value"].values()), None) for a in lr.get("attributes", [])}


def title(sid):
    """Session title from its transcript: custom title > ai title > cwd folder > short id."""
    found = {}
    for p in TRANSCRIPTS.glob(f"*/{sid}.jsonl"):
        for line in open(p, errors="replace"):
            for k, key in (("custom-title", "customTitle"), ("ai-title", "aiTitle")):
                if f'"type":"{k}"' in line:
                    found[k] = json.loads(line).get(key)
            if "cwd" not in found and '"cwd":"' in line:
                found["cwd"] = Path(json.loads(line).get("cwd") or "").name
    return found.get("custom-title") or found.get("ai-title") or found.get("cwd") or sid[:8]


def calls(path, subs=None, main=True):
    """Transcript -> ordered events: call (context size, output), user (prompt size), compact, sub (subagent run)."""
    ev, idx = [], {}
    turn = None if main else {"k": "edits", "edits": []}  # subagent: all its edits go to one bucket, returned last
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t, ts = d.get("type"), d.get("timestamp")
        if main and d.get("isSidechain"):
            continue
        if t == "assistant":
            m = d.get("message") or {}
            u = m.get("usage") or {}
            x = {"ctx": sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
                 "out": int(u.get("output_tokens") or 0)}
            if m.get("id") in idx:  # one message is logged once per content block
                ev[idx[m["id"]]].update(x)
            else:
                idx[m.get("id")] = len(ev)
                ev.append({"k": "call", "t": ts, "model": m.get("model"), "req": d.get("requestId"), **x})
            for b in m.get("content") or []:
                if main and turn and isinstance(b, dict) and b.get("type") in ("text", "tool_use"):  # what the model did, for turns without edits
                    i = b.get("input") or {}
                    turn["acts"].append(b["text"] if b["type"] == "text" else f"{b.get('name')}: {i.get('command') or i.get('file_path') or i.get('pattern') or i.get('query') or i.get('description') or ''}")
                    turn["acts"][-1] = str(turn["acts"][-1])[:ACT_CHARS]
                if turn and isinstance(b, dict) and b.get("type") == "tool_use":
                    i, cmd = b.get("input") or {}, str((b.get("input") or {}).get("command") or "")
                    if b.get("name") in ("Edit", "Write", "NotebookEdit") or WRITES.search(cmd):
                        turn["edits"].append(f"{b['name']} {i.get('file_path') or ''}: {str(i.get('new_string') or i.get('content') or cmd)[:EDIT_CHARS]}")
                if subs and isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") in subs:
                    ev.append(subs[b["id"]])
        elif t == "user" and main and not d.get("isMeta") and not d.get("isCompactSummary"):
            c = (d.get("message") or {}).get("content")
            text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")
            if text.strip() and not text.startswith(SKIP_PROMPTS):
                turn = {"k": "user", "t": ts, "chars": len(text), "text": text[:EXCERPT], "uuid": d.get("uuid"), "edits": [], "acts": []}
                ev.append(turn)
        elif t == "system" and d.get("subtype") == "compact_boundary":
            cm = d.get("compactMetadata") or {}
            ev.append({"k": "compact", "t": ts, "pre": cm.get("preTokens"), "post": cm.get("postTokens"), "trigger": cm.get("trigger")})
    return ev if main else ev + [turn]


def ctx_seg(a):
    """Context in base-input-price token units: [cache reads x0.1, cache writes + uncached input]."""
    n = lambda k: int(a.get(k) or 0)
    w5, w1 = n("cache_creation_5m_tokens"), n("cache_creation_1h_tokens")
    if not w5 and not w1:
        w5 = n("cache_creation_tokens")
    return [round(n("cache_read_tokens") * PRICE["read"]), round(w5 * PRICE["write_5m"] + w1 * PRICE["write_1h"] + n("input_tokens") * PRICE["input"])]


def ctx_cost(a):
    """Share of a request's cost_usd that paid for its context (input, cache reads, cache writes) rather than output."""
    n = lambda k: int(a.get(k) or 0)
    w5, w1 = n("cache_creation_5m_tokens"), n("cache_creation_1h_tokens")
    if not w5 and not w1:
        w5 = n("cache_creation_tokens")
    ctx = n("input_tokens") * PRICE["input"] + n("cache_read_tokens") * PRICE["read"] + w5 * PRICE["write_5m"] + w1 * PRICE["write_1h"]
    tot = ctx + n("output_tokens") * PRICE["output"]
    return float(a.get("cost_usd") or 0) * ctx / tot if tot else 0.0


def timeline(sid):
    p = next(TRANSCRIPTS.glob(f"*/{sid}.jsonl"), None)
    if not p:
        return {"events": []}
    subs = {}
    for m in (p.with_suffix("") / "subagents").glob("*.meta.json"):
        t = m.with_name(m.name.replace(".meta.json", ".jsonl"))
        if not t.exists():  # meta written before the transcript, or transcript moved
            continue
        meta = json.loads(m.read_text())
        sev = calls(t, main=False)
        if not sev:
            continue
        cs = [e for e in sev if e["k"] == "call"]
        subs[meta.get("toolUseId")] = {"k": "sub", "desc": meta.get("description"), "model": meta.get("model"),
                                       "ctx": [c["ctx"] for c in cs], "out": sum(c["out"] for c in cs), "reqs": [c["req"] for c in cs], "edits": sev[-1]["edits"]}
    ev = calls(p, subs)
    # cost per call: transcripts have no cost, telemetry api_request has it per request_id
    ts = sorted(e["t"] for e in ev if e.get("t"))
    cost, ccost, seg, compacts = {}, {}, {}, []
    if ts:
        d0, d1 = (datetime.fromisoformat(t.replace("Z", "+00:00")).date() for t in (ts[0], ts[-1]))
        for i in range(-1, (d1 - d0).days + 2):
            for a in records((d0 + timedelta(days=i)).isoformat()):
                if a.get("event.name") == "api_request" and a.get("session.id") == sid:
                    cost[a.get("request_id")] = float(a.get("cost_usd") or 0)
                    ccost[a.get("request_id")] = ctx_cost(a)
                    seg[a.get("request_id")] = ctx_seg(a)
                    if a.get("query_source") == "compact":  # the summarizing call is not in the transcript
                        compacts.append(a)
    for e in ev:
        if e["k"] == "call":
            r = e.pop("req"); e["cost"], e["ccost"], e["seg"] = cost.get(r), ccost.get(r), seg.get(r)
        elif e["k"] == "sub":
            rs = e.pop("reqs"); cs = [cost.get(r) for r in rs]; e["ccost"] = sum(ccost.get(r) or 0 for r in rs); e["wctx"] = [sum(seg[r]) if r in seg else None for r in rs]
            e["cost"], e["missing"] = sum(c for c in cs if c is not None), sum(c is None for c in cs)
        elif e["k"] == "compact" and compacts and e.get("t"):  # nearest compact request in time
            sec = lambda a: abs((datetime.fromisoformat(a["event.timestamp"].replace("Z", "+00:00")) - datetime.fromisoformat(e["t"].replace("Z", "+00:00"))).total_seconds())
            a = min(compacts, key=sec)
            if sec(a) < 120:
                compacts.remove(a)
                e["cost"], e["ccost"], e["read"] = float(a.get("cost_usd") or 0), ctx_cost(a), int(a.get("cache_read_tokens") or 0); e["seg"] = ctx_seg(a)
                e["fresh"] = int(a.get("input_tokens") or 0) + int(a.get("cache_creation_tokens") or 0)
    categorize(ev)
    return {"events": ev}


def categorize(ev):
    """Each prompt gets a column (d1, cached): with edits -> Runtime/UI/Infra/Docs; without -> Planning or None; d1 down -> unset."""
    cache = {}
    if CATEGORIES.exists():
        for line in open(CATEGORIES):
            r = json.loads(line); cache[r["uuid"]] = r
    turns, cur = [], None
    for e in ev:  # a prompt's edits include those of the subagents it launched
        if e["k"] == "user":
            cur = e; turns.append(e)
        elif e["k"] == "sub":
            sub_edits = e.pop("edits")
            if cur: cur["edits"] += sub_edits
    for e in turns:
        edits, acts = e.pop("edits"), e.pop("acts")
        if not edits and not acts:
            e["cat"] = None
            continue
        if e["uuid"] not in cache:
            if edits:
                state = ("User prompt: " + e["text"] + "\nChanges made:\n" + "\n".join(edits))[:STATE_CHARS]
                body = {"state": state, "q": "Which part of the codebase did these changes affect?", "type": "choice", "opts": CATS}
            else:  # no file written: was it planning work or trivial?
                state = ("User prompt: " + e["text"] + "\nModel did (no files changed):\n" + "\n".join(acts))[:STATE_CHARS]
                body = {"state": state, "q": "Was this turn planning work or something trivial?", "type": "choice", "opts": PLAN}
            try:
                a = json.load(urllib.request.urlopen(urllib.request.Request(D1, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=5))["answer"]
            except Exception:
                continue
            pr = a.get("probabilities") or {}
            cache[e["uuid"]] = r = {"uuid": e["uuid"], "cat": max(pr, key=pr.get), "p": round(max(pr.values()), 2)}
            if e is not turns[-1]:  # the last prompt may still be running: classify again next time
                with open(CATEGORIES, "a") as f:
                    f.write(json.dumps(r) + "\n")
        c = cache[e["uuid"]]
        e["cat"], e["catp"] = (None if c["cat"] == "None" else c["cat"]), c["p"]


def subagents(sid):
    """Telemetry has no subagent-completed event; each subagent run leaves a meta.json next to the session transcript."""
    return sum(1 for _ in TRANSCRIPTS.glob(f"*/{sid}/subagents/*.meta.json"))


def window():
    end = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(hours=WINDOW_H)
    hours = [{"h": (start + timedelta(hours=i)).hour, "cost": 0.0, "vol": 0} for i in range(WINDOW_H)]
    s = defaultdict(lambda: {"cost": 0.0, "vol": 0, "calls": 0, "subagents": 0, "subcost": 0.0, "t0": None, "t1": None, "name": None})
    # file date may be UTC or local: read one extra day each side, the timestamp filter decides
    days = [(start.date() + timedelta(days=i)).isoformat() for i in range(-1, (end.date() - start.date()).days + 2)]
    for a in (r for day in days for r in records(day)):
        e, sid, ts = a.get("event.name"), a.get("session.id"), a.get("event.timestamp")
        t = ts and datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if not t or not start <= t < end:
            continue
        x = s[sid]
        if ts:
            x["t0"], x["t1"] = min(filter(None, [x["t0"], ts])), max(filter(None, [x["t1"], ts]))
        if e == "api_request":
            vol = sum(int(a.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"))
            cost = float(a.get("cost_usd") or 0)
            h = int((t - start).total_seconds() // 3600)
            hours[h]["cost"] += cost; hours[h]["vol"] += vol
            x["cost"] += cost; x["vol"] += vol; x["calls"] += 1
            if str(a.get("query_source") or "").startswith("agent:"):  # subagent calls share the parent's session.id
                x["subcost"] += cost
    sessions = sorted(({"id": k, **v, "name": title(k), "subagents": subagents(k)} for k, v in s.items() if v["calls"]), key=lambda v: -v["cost"])
    return {"day": f"last {WINDOW_H}h", "hours": hours, "sessions": sessions}


_live = None


def live():
    global _live
    if _live is None:
        spec = importlib.util.spec_from_file_location("otm_live", LIVE_PY)
        _live = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_live)
    return _live


def api(tool, query):
    """GET /api/<tool>?k=v -> (status, body): query values typed by the tool's inputSchema (arrays: repeat k or comma-separate)."""
    lv = live()
    if tool not in lv.TOOL_ARGS:
        return 404, {"error": f"unknown tool {tool}; known {sorted(lv.TOOL_ARGS)}"}
    args = {}
    try:
        for k, vs in parse_qs(query).items():
            typ = lv.TOOL_ARGS[tool].get(k, {}).get("type")
            args[k] = (int(vs[-1]) if typ == "integer" else vs[-1].lower() in ("1", "true", "yes") if typ == "boolean"
                       else [x for v in vs for x in v.split(",") if x] if typ == "array" else vs[-1])
        is_err, data = lv.call_tool(tool, args)
    except (lv.ArgError, ValueError) as e:
        return 400, {"error": str(e)}
    if tool == "agents" and not is_err:
        mark_inline(data)
    return (200, data) if not is_err else (404, {"error": data})


_shape = {}  # meta.json path -> requestShape (fixed once the subagent is spawned)


def mark_inline(data):
    """live.py agents rows lack the spawn shape: add inline=true for subagents whose meta.json has requestShape "foreground" (parent blocked until it returns)."""
    rows, sid = data.get("agents") or [], (data.get("session") or {}).get("sid")
    if not sid or len(rows) < 2:
        return
    for f in TRANSCRIPTS.glob(f"*/{sid}*/subagents/agent-*.meta.json"):
        if str(f) not in _shape:
            try:
                _shape[str(f)] = json.loads(f.read_text()).get("requestShape")
            except (OSError, ValueError):
                continue
    fg = {Path(f).name[6:-10] for f, v in _shape.items() if v == "foreground" and f"/{sid}" in f}
    for r in rows[1:]:
        if any(a.startswith(r["id"]) for a in fg):
            r["inline"] = True


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        u, code = urlparse(self.path), 200
        if u.path == "/session.json":
            body = json.dumps(timeline(parse_qs(u.query).get("id", [""])[0])).encode()
        elif u.path == "/data.json":
            body = json.dumps(window()).encode()
        elif u.path == "/api/orch_ux":
            code, body = (200, ORCH_UX.read_bytes()) if ORCH_UX.exists() else (404, json.dumps({"error": f"missing {ORCH_UX}"}).encode())
        elif u.path.startswith("/api/"):
            code, data = api(u.path[5:], u.query)
            body = json.dumps(data).encode()
        else:
            return super().do_GET()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/console":
            return self.send_error(404)
        body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_EVENT))
        with open(LOG, "a") as f:
            f.write(body.decode("utf-8", "replace").replace("\n", " ") + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"http://{HOST}:{PORT}/  data={DATA}  log={LOG}", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
