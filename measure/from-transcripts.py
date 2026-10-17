#!/usr/bin/env python3
"""Summarizes local Claude Code session logs into usage JSON: cost, tokens, models, projects, tools, turns.
Reads only metadata (usage, model, tool names, folder, timestamps); prompts, replies and code are never copied.
Usage: python3 from-transcripts.py [days] > usage.json"""
import collections, glob, json, os, sys, time

LOGS = os.path.expanduser("~/.claude/projects/**/*.jsonl")
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
TOP = 12  # rows kept per ranking
# USD per million tokens: input, output, cache read, cache write. First substring match wins.
# Fitted to the cost Claude Code itself reports (cost-state records); fable and haiku are guesses.
PRICES = {
    "opus-5-5": (5, 20, 0.25, 7.5),
    "opus": (5, 25, 0.5, 10),
    "sonnet": (3, 15, 0.3, 3.75),
    "haiku-5": (0.1, 0.5, 0.01, 0.125),
    "haiku": (1, 5, 0.1, 1.25),
    "fable": (10, 50, 1, 12.5),
}
DEFAULT_PRICE = "opus"

def price(model):
    return next((p for k, p in PRICES.items() if k in model), PRICES[DEFAULT_PRICE])

def cost(model, u):
    pin, pout, pread, pwrite = price(model)
    return (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout
            + u.get("cache_read_input_tokens", 0) * pread + u.get("cache_creation_input_tokens", 0) * pwrite) / 1e6

def project(cwd):
    parts = [p for p in (cwd or "?").replace(os.path.expanduser("~"), "").split("/") if p]
    if not parts or parts[0] == "tmp":
        return "(scratch)"
    return "/".join(parts[-2:]) if parts[0] == "projects" and len(parts) > 2 else "/".join(parts[-1:])

since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - DAYS * 86400))
calls = {}  # requestId -> call; a response is logged once per content block
prompts = collections.Counter()  # (session, day) -> human prompts
sessions = {}
for path in glob.glob(LOGS, recursive=True):
    if os.path.getmtime(path) < time.time() - DAYS * 86400:
        continue
    for line in open(path, errors="replace"):
        if '"assistant"' not in line and '"user"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp", "")
        if ts < since:
            continue
        sid = d.get("sessionId")
        if d.get("type") == "user" and not d.get("isMeta") and not d.get("isSidechain"):
            c = d.get("message", {}).get("content")
            if isinstance(c, str) or (isinstance(c, list) and any(b.get("type") == "text" for b in c)):
                prompts[sid] += 1
                sessions.setdefault(sid, project(d.get("cwd")))
        if d.get("type") != "assistant":
            continue
        m = d["message"]
        u, model = m.get("usage"), m.get("model", "?")
        if not u or model == "<synthetic>":
            continue
        call = calls.setdefault(d.get("requestId") or m.get("id"), {
            "ts": ts, "session": sid, "project": project(d.get("cwd")), "model": model,
            "sub": bool(d.get("isSidechain")), "tools": set(), "u": u})
        call["u"] = u
        call["tools"].update(b["name"] for b in m.get("content", []) if b.get("type") == "tool_use")

by_day = collections.defaultdict(lambda: collections.Counter())
models, tools, tool_calls = collections.Counter(), collections.Counter(), collections.Counter()
proj = collections.defaultdict(lambda: {"cost": 0, "calls": 0, "sessions": set()})
sess = collections.defaultdict(lambda: {"cost": 0, "calls": 0, "project": "", "day": "", "sub": 0})
tok = collections.Counter()
for c in calls.values():
    usd = cost(c["model"], c["u"])
    name = c["model"].replace("claude-", "").split("[")[0]
    by_day[c["ts"][:10]][name] += usd
    models[name] += usd
    for t in c["tools"] or {"(reply)"}:
        tools[t] += usd / max(1, len(c["tools"]))
        tool_calls[t] += 1
    p = proj[c["project"]]
    p["cost"] += usd; p["calls"] += 1; p["sessions"].add(c["session"])
    s = sess[c["session"]]
    s["cost"] += usd; s["calls"] += 1; s["project"] = c["project"]; s["day"] = s["day"] or c["ts"][:10]
    s["sub"] += usd if c["sub"] else 0
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        tok[k] += c["u"].get(k, 0)

for sid, s in sess.items():
    s["turns"] = prompts.get(sid, 0)
total = sum(models.values())
json.dump({
    "generated": time.strftime("%Y-%m-%d"), "days": DAYS, "prices": "list price estimate, see PRICES in from-transcripts.py",
    "totals": {"cost": round(total, 2), "calls": len(calls), "sessions": len(sess),
               "turns": sum(prompts.values()), "projects": len(proj),
               "subagent_cost": round(sum(s["sub"] for s in sess.values()), 2)},
    "tokens": dict(tok),
    "by_day": [{"day": d, **{k: round(v, 2) for k, v in by_day[d].items()}} for d in sorted(by_day)],
    "models": {k: round(v, 2) for k, v in models.most_common()},
    "projects": [{"name": k, "cost": round(v["cost"], 2), "calls": v["calls"], "sessions": len(v["sessions"])}
                 for k, v in sorted(proj.items(), key=lambda x: -x[1]["cost"])][:TOP],
    "tools": [{"name": k, "cost": round(v, 2), "calls": tool_calls[k]} for k, v in tools.most_common(TOP)],
    "sessions": sorted(({"cost": round(s["cost"], 2), "calls": s["calls"], "turns": s["turns"],
                         "project": s["project"], "day": s["day"], "subagent_cost": round(s["sub"], 2)}
                        for s in sess.values()), key=lambda s: -s["cost"]),
}, sys.stdout, indent=1)
