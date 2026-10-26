#!/usr/bin/env python3
"""MCP usage from Claude Code transcripts and configs: calls, errors, context cost per server and tool. Specs: mcp-usage/METHOD.md (M-*).

python3 04-auto-analysis/mcp-usage/mcp_usage.py [--days N] [--root DIR] [--claude-json FILE] [--config PATH] [--out DIR]
Reads ~/.claude/projects/**/*.jsonl (tool_use/tool_result blocks, MCP attachments) + server names from ~/.claude.json and
each known project's .mcp.json, writes mcp_usage.jsonl.
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir

DAYS = 7
ROOT = "~/.claude/projects"
CLAUDE_JSON = "~/.claude.json"
CHARS_PER_TOKEN = 4      # M-size: token estimate = characters / 4
IMAGE_TOKENS = 1500      # M-size: flat estimate per image block in a tool result
PREFIX = "mcp__"         # M-name: mcp__<server>__<tool>
HARNESS = "claude-code"
ISO = "%Y-%m-%dT%H:%M:%SZ"


def norm(name):
    """M-name: Claude Code turns a configured server name into its tool prefix by replacing [^A-Za-z0-9_-] with '_'."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def split(tool):
    """M-name: 'mcp__srv__tool' -> ('srv', 'tool'); the first '__' after the prefix separates them."""
    srv, _, t = tool[len(PREFIX):].partition("__")
    return srv, t or None


def tokens(x):
    """M-size: estimated tokens of a tool_use input (JSON) or a tool_result content (str or blocks)."""
    if isinstance(x, str):
        return -(-len(x) // CHARS_PER_TOKEN)
    if isinstance(x, list):
        return sum(IMAGE_TOKENS if isinstance(b, dict) and b.get("type") == "image"
                   else tokens(b.get("text", "") if isinstance(b, dict) and "text" in b else json.dumps(b)) for b in x)
    return tokens(json.dumps(x)) if x is not None else 0


def configured(path):
    """M-config: server names only (never commands, env or headers) -> {norm name: 'enabled'|'disabled'}."""
    try:
        with open(os.path.expanduser(path)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out, disabled = {}, set()
    scopes = [d] + list((d.get("projects") or {}).values())
    for proj in (d.get("projects") or {}):
        try:
            with open(os.path.join(proj, ".mcp.json")) as f:
                scopes.append(json.load(f))
        except (OSError, ValueError):
            pass
    for s in scopes:
        if isinstance(s, dict):
            out.update((norm(n), "enabled") for n in (s.get("mcpServers") or {}))
            disabled.update(norm(n) for n in (s.get("disabledMcpServers") or []) + (s.get("disabledMcpjsonServers") or []))
    out.update((n, "disabled") for n in disabled)  # M-config: disabled anywhere wins (it is off where it was disabled)
    return out


def scan(root, since):
    """M-scan: tool calls by tool_use id, results by tool_use id, MCP servers loaded per session."""
    uses, results, loaded = {}, {}, {}
    for path in glob.glob(os.path.join(os.path.expanduser(root), "**", "*.jsonl"), recursive=True):
        if os.path.getmtime(path) < since.timestamp():
            continue
        with open(path, errors="replace") as f:
            for line in f:
                if '"tool_use' not in line and '"mcp_instructions_delta"' not in line and '"deferred_tools_delta"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    t = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
                except (ValueError, KeyError, AttributeError):
                    continue
                if t < since:
                    continue
                sid = d.get("sessionId")
                a = d.get("attachment") or {}
                if a.get("type") == "mcp_instructions_delta":  # M-loaded: servers announced to the model
                    loaded.setdefault(sid, set()).update(norm(n) for n in a.get("addedNames") or [])
                elif a.get("type") == "deferred_tools_delta":
                    loaded.setdefault(sid, set()).update(split(n)[0] for n in a.get("addedNames") or [] if n.startswith(PREFIX))
                c = (d.get("message") or {}).get("content")
                for b in c if isinstance(c, list) else []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and b.get("id"):
                        uses[b["id"]] = {"name": b.get("name") or "", "sid": sid, "ts": t, "in": tokens(b.get("input"))}
                    elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                        results[b["tool_use_id"]] = (tokens(b.get("content")), bool(b.get("is_error")))
    return uses, results, loaded


def blank(server, tool):
    return {"v": 1, "harness": HARNESS, "kind": "tool" if tool else "server", "server": server, "tool": tool,
            "calls": 0, "errors": 0, "input_tokens_est": 0, "result_tokens_est": 0, "context_share": 0.0,
            "sessions": set(), "first": None, "last": None}


def aggregate(uses, results, loaded, config):
    """M-agg: one record per (server, tool) and one per server; context_share over all tool calls (MCP and built-in)."""
    total, rows = 0, {}
    for uid, u in uses.items():
        rt, err = results.get(uid, (0, False))
        total += u["in"] + rt
        if not u["name"].startswith(PREFIX):
            continue
        srv, tool = split(u["name"])
        for key in ((srv, None), (srv, tool)):
            r = rows.setdefault(key, blank(*key))
            r["calls"] += 1
            r["errors"] += err
            r["input_tokens_est"] += u["in"]
            r["result_tokens_est"] += rt
            r["sessions"].add(u["sid"])
            r["first"] = min(r["first"] or u["ts"], u["ts"])
            r["last"] = max(r["last"] or u["ts"], u["ts"])
    servers = {s for s, _ in rows} | set(config) | {s for v in loaded.values() for s in v}
    out = []
    for s in sorted(servers):
        for key in [(s, None)] + sorted(k for k in rows if k[0] == s and k[1]):
            r = rows.get(key) or blank(*key)
            ctx = r["input_tokens_est"] + r["result_tokens_est"]
            r.update(context_share=round(ctx / total, 6) if total else 0.0, sessions=len(r["sessions"]),
                     first=r["first"] and r["first"].strftime(ISO), last=r["last"] and r["last"].strftime(ISO))
            server_row = key[1] is None
            r["config"] = config.get(s, "none") if server_row else None  # M-config
            r["loaded_sessions"] = sum(s in v for v in loaded.values()) if server_row else None  # M-loaded
            r["never_called"] = r["calls"] == 0 if server_row else None  # M-unused
            out.append(r)
    return out


def run(root, claude_json, since):
    return aggregate(*scan(root, since), configured(claude_json))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--root", help=f"transcripts dir (default: config readers.paths.claude-code, else {ROOT})")
    ap.add_argument("--claude-json", default=CLAUDE_JSON)
    ap.add_argument("--config")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config(a.config)
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=a.days)
    recs = run(a.root or cfg["readers"]["paths"].get(HARNESS) or ROOT, a.claude_json, since)
    out = a.out or data_dir(cfg)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "mcp_usage.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    srv = [r for r in recs if r["kind"] == "server"]
    top = sorted(srv, key=lambda r: -(r["input_tokens_est"] + r["result_tokens_est"]))[:3]
    print(f"mcp_usage: {len(srv)} servers, {sum(r['calls'] for r in srv)} calls, "
          f"{sum(r['never_called'] for r in srv)} never called; top by context: "
          + (", ".join(f"{r['server']} {r['input_tokens_est'] + r['result_tokens_est']} tok "
                       f"({r['context_share']:.1%}, {r['calls']} calls, {r['errors']} err)" for r in top if r["calls"]) or "none")
          + f" -> {out}")


if __name__ == "__main__":
    main()
