#!/usr/bin/env python3
"""Read-only MCP server (stdio, JSON-RPC 2.0, one message per line) over the analysis outputs.

Tools: summary outliers metric session impact decisions recommendations usage_breakdown coverage. Reads analysis(.decided).json,
sessions.jsonl, impact_summary.json, decisions.jsonl through the `mcp.source` connector.
Never returns raw events or repo paths. Usage: mcp/AGENTS.md.
"""
import argparse, json, os, re, sys

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector

MAX_ITEMS = 50          # hard cap on items per page
DEFAULT_LIMIT = 10      # page size when the caller gives none
MAX_RESPONSE_TOKENS = 2000  # every tool result is trimmed to this (~chars/CHARS_PER_TOKEN)
CHARS_PER_TOKEN = 4
SUMMARY_ROWS = 10       # rows per by_* list in summary
BREAKDOWN_ROWS = 10     # rows returned by usage_breakdown
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]  # newest first; client's echoed if listed
SERVER_INFO = {"name": "opentokenmini", "version": "0.2"}
PRIVATE_KEYS = {"repo"}  # dropped from every record before it leaves the server


def files_source(name, cfg):
    """Default source: parsed JSON (.json) or list of records (.jsonl) from the data dir; None if missing."""
    path = os.path.join(data_dir(cfg), name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        if name.endswith(".jsonl"):
            return [json.loads(l) for l in f if l.strip()]
        return json.load(f)


SOURCES = {"files": files_source}


class ToolError(Exception):
    """In-band tool failure (missing file, unknown id): result with isError."""


class ArgError(Exception):
    """Bad arguments: JSON-RPC -32602."""


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in PRIVATE_KEYS}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


def page(items, args):
    offset = args.get("offset", 0)
    limit = min(MAX_ITEMS, args.get("limit", DEFAULT_LIMIT))  # types and minimums checked in check_args
    nxt = offset + limit
    return {"items": items[offset:nxt], "total": len(items), "offset": offset,
            "next_offset": nxt if nxt < len(items) else None}


def size_tokens(o):
    return len(json.dumps(o)) // CHARS_PER_TOKEN


def fit(data):
    """Trim a result to MAX_RESPONSE_TOKENS: drop trailing page items (next_offset follows) or list rows."""
    if size_tokens(data) <= MAX_RESPONSE_TOKENS or not isinstance(data, dict):
        return data
    if isinstance(data.get("items"), list):
        while len(data["items"]) > 1 and size_tokens(data) > MAX_RESPONSE_TOKENS:
            data["items"].pop()
        data["next_offset"] = data["offset"] + len(data["items"]) if data["offset"] + len(data["items"]) < data["total"] else None
        return data
    lists = [k for k, v in data.items() if isinstance(v, list)]
    while lists and size_tokens(data) > MAX_RESPONSE_TOKENS:
        k = max(lists, key=lambda k: len(data[k]))
        if len(data[k]) <= 1:
            break
        data[k].pop()
        data.setdefault("truncated", {})[k] = data["truncated"].get(k, len(data[k]) + 1)
    return data


def compact_decision(d):
    """Decision -> {choice, p} (probability of the chosen option)."""
    if not isinstance(d, dict):
        return d
    probs = d.get("probabilities") or {}
    return {"choice": d.get("choice"), "p": probs.get(d.get("choice"))}


def match(rec, args, keys):
    return all(args.get(k) is None or rec.get(f) == args[k] for k, f in keys.items())


class Server:
    def __init__(self, cfg):
        self.cfg = cfg
        self.load_raw = connector(SOURCES, cfg["mcp"]["source"], "mcp.source")

    def load(self, name, need=True):
        data = self.load_raw(name, self.cfg)
        if data is None and need:
            raise ToolError(f"{name} not found; run the stage that writes it")
        return data

    def analysis(self):
        return self.load("analysis.decided.json", need=False) or self.load("analysis.json")

    # tools
    def summary(self, a):
        an = self.analysis()
        by = an.get("by", {})
        keys = ("harness", "model", "project")
        out = {"generated": an.get("generated"), "period": an.get("period"), "filters": an.get("filters"),
                "totals": an.get("totals"),
                **{f"by_{k}": by.get(k, [])[:MAX_ITEMS] for k in keys},
                # lists longer than MAX_ITEMS: name -> full length (only the first MAX_ITEMS are returned)
                "truncated": {k: len(by.get(k, [])) for k in keys if len(by.get(k, [])) > SUMMARY_ROWS}}
        for k in keys:
            out[f"by_{k}"] = out[f"by_{k}"][:SUMMARY_ROWS]
        out["by_model"] = [m | {"cost_per_call": round(m["cost"] / m["calls"], 5) if m.get("calls") else None,
                                "cost_per_session": round(m["cost"] / m["sessions"], 4) if m.get("sessions") else None}
                           if isinstance(m, dict) and isinstance(m.get("cost"), (int, float)) else m
                           for m in out["by_model"]]
        if a.get("days") or a.get("since"):
            out["window"] = self.window(by.get("day", []), a)
        return out

    def window(self, days, a):
        """Spend per harness over the last `days` days (ending at the newest day) or since a YYYY-MM-DD date."""
        if not days:
            return {"since": None, "days": 0, "cost": 0, "by_harness": {}}
        if a.get("since"):
            since = a["since"]
        else:
            import datetime
            last = datetime.date.fromisoformat(max(d["day"] for d in days))
            since = (last - datetime.timedelta(days=a["days"] - 1)).isoformat()
        rows = [d for d in days if d["day"] >= since]
        hs = {}
        for d in rows:
            for h, c in d.items():
                if h != "day" and isinstance(c, (int, float)):
                    hs[h] = hs.get(h, 0) + c
        return {"since": since, "days": len(rows), "cost": round(sum(hs.values()), 4),
                "by_harness": {h: round(c, 4) for h, c in sorted(hs.items(), key=lambda x: -x[1])},
                "note": "window applies to `window` only; totals and by_* are the full period"}

    def recommendations(self, a):
        """analysis recommendations joined to their latest decision by the shared id `<rec id>/<harness>`."""
        latest = {}
        for d in self.load("decisions.jsonl", need=False) or []:
            if d.get("point") == "recommendation":
                latest[d.get("subject")] = d
        rows = []
        for r in self.analysis().get("recommendations", []):
            if not match(r, a, {"harness": "harness", "verdict": "verdict"}):
                continue
            d = latest.get(r.get("id"))
            row = {k: r.get(k) for k in ("id", "candidate", "harness", "verdict", "p_yes")}
            if row["p_yes"] is None and d:
                row["p_yes"] = (d.get("probabilities") or {}).get("yes")
            row["decided"] = d.get("ts") if d else None
            if a.get("detail"):
                row["evidence"] = r.get("evidence")
            rows.append(row)
        return page(rows, a)

    def outliers(self, a):
        rows = [o for o in self.analysis().get("outliers", []) if match(o, a, {"metric": "metric", "group": "group"})]
        if not a.get("detail"):
            rows = [{k: compact_decision(v) if k == "decision" else v for k, v in o.items() if k != "session_ids"}
                    for o in rows]
        return page(rows, a)

    def metric(self, a):
        rows = [m for m in self.analysis().get("metrics", []) if match(m, a, {"id": "id", "group": "group"})]
        return page(rows, a)

    def session(self, a):
        rows = self.load("sessions.jsonl")
        if a.get("session_id"):
            hit = [s for s in rows if s.get("session_id") == a["session_id"]]
            if not hit:
                raise ToolError(f"session {a['session_id']} not found")
            return hit[0]
        rows = [s for s in rows if match(s, a, {"harness": "harness", "project": "project"})]
        total = lambda s: (s.get("cost") or {}).get("total") if isinstance(s.get("cost"), dict) else None
        rows.sort(key=lambda s: -(total(s) if isinstance(total(s), (int, float)) else 0))
        return page([{k: s.get(k) for k in ("session_id", "harness", "project", "start", "calls")}
                     | {"cost": total(s)} for s in rows], a)

    def impact(self, a):
        im = self.load("impact_summary.json")
        by = a.get("by", "repo")
        if by not in ("repo", "harness"):
            raise ToolError("by must be repo or harness")
        head = {k: v for k, v in im.items() if not k.startswith("by_")}
        return head | {"by": by} | page(im.get(f"by_{by}", []), a)

    def decisions(self, a):
        rows = [d for d in self.load("decisions.jsonl") if match(d, a, {"point": "point", "subject": "subject"})]
        if not a.get("detail"):
            rows = [{k: d.get(k) for k in ("ts", "point", "subject")} | compact_decision(d) for d in rows]
        return page(rows[::-1], a)  # newest first

    def usage_breakdown(self, a):
        """Top BREAKDOWN_ROWS tools (cost, calls, cost share), MCP servers (calls, error rate) or subagent cost share per harness."""
        by = a.get("by", "tool")
        if by == "subagent":
            rows = self.load("sessions.jsonl")
            if a.get("days"):
                import datetime
                starts = [s["start"][:10] for s in rows if s.get("start")]
                since = (datetime.date.fromisoformat(max(starts)) - datetime.timedelta(days=a["days"] - 1)).isoformat() if starts else ""
                rows = [s for s in rows if (s.get("start") or "")[:10] >= since]
            hs = {}
            for s in rows:
                c = s.get("cost") if isinstance(s.get("cost"), dict) else {}
                h = hs.setdefault(s.get("harness"), {"harness": s.get("harness"), "sessions": 0, "cost": 0.0, "subagent_cost": 0.0})
                h["sessions"] += 1
                h["cost"] += c.get("total") or 0
                h["subagent_cost"] += s.get("subagent_cost") or 0
            out = sorted(hs.values(), key=lambda h: -h["cost"])
            for h in out:
                h["subagent_share"] = round(h["subagent_cost"] / h["cost"], 4) if h["cost"] else None
                h["cost"], h["subagent_cost"] = round(h["cost"], 4), round(h["subagent_cost"], 4)
            tot, sub = sum(h["cost"] for h in out), sum(h["subagent_cost"] for h in out)
            return {"by": by, "days": a.get("days"), "cost": round(tot, 4), "subagent_cost": round(sub, 4),
                    "subagent_share": round(sub / tot, 4) if tot else None, "rows": out[:BREAKDOWN_ROWS]}
        if a.get("days"):
            raise ToolError("days applies to by=subagent only; tool and mcp are full-period aggregates")
        an = self.analysis()
        rows = an.get("by", {}).get(by, [])
        if by == "tool":
            total = ((an.get("totals") or {}).get("cost") or {}).get("total") or 0
            out = [{"name": r.get("name"), "cost": round(r.get("cost") or 0, 4), "calls": r.get("calls"),
                    "share": round((r.get("cost") or 0) / total, 4) if total else None} for r in rows]
            out.sort(key=lambda r: -r["cost"])
        else:
            out = [{k: r.get(k) for k in ("server", "calls", "errors", "error_rate")} for r in rows]
            out.sort(key=lambda r: -(r["calls"] or 0))
        return {"by": by, "total": len(out), "rows": out[:BREAKDOWN_ROWS]}

    def coverage(self, a):
        cov = self.analysis().get("coverage", {})
        if a.get("harness"):
            if a["harness"] not in cov:
                raise ToolError(f"no coverage for {a['harness']}; known {sorted(cov)}")
            return {a["harness"]: cov[a["harness"]]}
        return cov


PAGING = {"offset": {"type": "integer", "minimum": 0},
          "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS}}
S = {"type": "string"}
DETAIL = {"detail": {"type": "boolean"}}  # false (default): compact rows; true: full records
TOOLS = [
    ("summary", "Period, totals (cost/tokens/calls/sessions) and top spend by harness, model (with cost per call/session), project; "
     "days (last N days) or since (YYYY-MM-DD) adds per-harness spend for that window.",
     {"days": {"type": "integer", "minimum": 1}, "since": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}}),
    ("outliers", "Flagged outliers (robust z), newest analysis; filter by metric id or group.",
     {"metric": S, "group": S, **DETAIL, **PAGING}),
    ("metric", "Metric values per group (id like M-cache-hit-rate); no filter lists all.",
     {"id": S, "group": S, **PAGING}),
    ("session", "One session by session_id, or sessions by cost desc (filter harness, project).",
     {"session_id": S, "harness": S, "project": S, **PAGING}),
    ("impact", "Sessions linked to commits: totals and rows by repo label or harness.",
     {"by": {"type": "string", "enum": ["repo", "harness"]}, **PAGING}),
    ("decisions", "Decision-model answers, newest first; filter by point or subject.",
     {"point": S, "subject": S, **DETAIL, **PAGING}),
    ("recommendations", "Should-I-do-X answers: candidate change per harness with verdict (suggest/skip/unsure) and p_yes.",
     {"harness": S, "verdict": {"type": "string", "enum": ["suggest", "skip", "unsure"]}, **DETAIL, **PAGING}),
    ("usage_breakdown", "Top 10 tools by cost (calls, share of spend), MCP servers by calls (error rate), or subagent cost "
     "share per harness (default by=tool); days (last N days) only with by=subagent.",
     {"by": {"type": "string", "enum": ["tool", "mcp", "subagent"]}, "days": {"type": "integer", "minimum": 1}}),
    ("coverage", "Per-harness data coverage: events, sessions, sources, cost basis share, unpriced calls.",
     {"harness": S}),
]
TOOL_LIST = [{"name": n, "description": d,
              "inputSchema": {"type": "object", "properties": p, "additionalProperties": False}}
             for n, d, p in TOOLS]
TOOL_ARGS = {n: p for n, _, p in TOOLS}


def check_args(name, args):
    """Validate arguments against the tool's inputSchema properties; raise ArgError."""
    if not isinstance(args, dict):
        raise ArgError("arguments must be an object")
    for k, v in args.items():
        spec = TOOL_ARGS[name].get(k)
        if spec is None:
            raise ArgError(f"unknown argument {k!r}; allowed {sorted(TOOL_ARGS[name])}")
        if spec["type"] == "string" and not isinstance(v, str):
            raise ArgError(f"{k} must be a string")
        if spec["type"] == "integer" and (not isinstance(v, int) or isinstance(v, bool) or v < spec["minimum"]):
            raise ArgError(f"{k} must be an integer >= {spec['minimum']}")
        if spec["type"] == "boolean" and not isinstance(v, bool):
            raise ArgError(f"{k} must be a boolean")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], v):
            raise ArgError(f"{k} must match {spec['pattern']}")
        if "enum" in spec and v not in spec["enum"]:
            raise ArgError(f"{k} must be one of {spec['enum']}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, text):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}


def _initialize(params):
    want = params.get("protocolVersion")
    version = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}


METHODS = {"initialize": _initialize, "ping": lambda params: {}, "tools/list": lambda params: {"tools": TOOL_LIST}}


def _call_tool(srv, mid, params):
    name, args = params.get("name"), params.get("arguments", {})
    if not isinstance(name, str) or name not in TOOL_ARGS:
        return _err(mid, -32602, f"unknown tool: {name}")
    try:
        check_args(name, args)
    except ArgError as e:
        return _err(mid, -32602, str(e))
    try:
        data = fit(scrub(getattr(srv, name)(args)))
        return _ok(mid, {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False})
    except (ToolError, OSError, ValueError, KeyError) as e:
        return _ok(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})


def handle(srv, msg):
    """One JSON-RPC message -> response dict, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None
    if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _err(mid, -32600, "invalid request: needs jsonrpc 2.0 and a method")
    if not isinstance(params, dict):
        return _err(mid, -32602, "params must be an object")
    if method in METHODS:
        return _ok(mid, METHODS[method](params))
    if method != "tools/call":
        return _err(mid, -32601, f"method not found: {method}")
    return _call_tool(srv, mid, params)


def _respond(srv, line):
    """One input line -> response dict or None; never raises."""
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return _err(None, -32700, "parse error")
    if not isinstance(msg, dict):
        return _err(None, -32600, "invalid request")
    try:
        return handle(srv, msg)
    except Exception as e:  # never die on one request
        return None if "id" not in msg else _err(msg["id"], -32603, f"internal error: {type(e).__name__}")


def serve(srv, inp=sys.stdin, out=sys.stdout):
    for line in inp:
        resp = _respond(srv, line) if line.strip() else None
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    serve(Server(load_config(ap.parse_args().config)))


if __name__ == "__main__":
    main()
