#!/usr/bin/env python3
"""Context efficiency from Claude Code transcripts: growth, peaks, compactions, cache mix, re-reads, big tool outputs. Specs: context/METHOD.md (X-*).

python3 04-auto-analysis/context/context.py [--days N] [--root DIR] [--config PATH] [--out DIR]
Reads ~/.claude/projects/**/*.jsonl (usage, compact_boundary, tool_use/tool_result sizes; in memory only), writes context.json
(a small "readout" for readout.json + per-session detail). No file path, prompt or tool content is written.
"""
import argparse, glob, json, os, statistics, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ and readers/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
sys.path.insert(0, str(REPO / "02-measure" / "readers"))
from schemas.config import load_config, data_dir
from schemas.cost import load_prices, make_tokens, event_cost
from common import recent, ts_ok, project
from claude_code import SKIP_MODELS

DAYS = 30
ROOT = "~/.claude/projects"
HARNESS = "claude-code"
OUT = "context.json"
CHARS_PER_TOKEN = 4                      # X-size: token estimate = characters / 4
IMAGE_TOKENS = 1500                      # X-size: flat estimate per image block in a tool result
THRESHOLDS = (150_000, 250_000)          # X-peak: sessions whose peak ctx reaches these
CURVE_TURNS = (1, 10, 25, 50, 100, 200)  # X-curve: median ctx at these main-thread turns
CURVE_POINTS = 20                        # X-curve: per-session curve downsampled to this many points
TOP_TOOLS = 5                            # X-tools: tools with the most result tokens
TOP_SESSIONS = 20                        # detail: sessions listed (highest peak first)
READ_TOOL = "Read"                       # X-reread
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")  # X-reread: an edit to the file resets its read count
MAX_READOUT_BYTES = 400                  # X-readout: findings are dropped until the section fits


def tokens(x):
    """X-size: estimated tokens of a tool_result content (str or blocks)."""
    if isinstance(x, str):
        return -(-len(x) // CHARS_PER_TOKEN)
    if isinstance(x, list):
        return sum(IMAGE_TOKENS if isinstance(b, dict) and b.get("type") == "image"
                   else tokens(b.get("text", "") if isinstance(b, dict) and "text" in b else json.dumps(b)) for b in x)
    return tokens(json.dumps(x)) if x is not None else 0


def scan(root, since):
    """X-scan: per file, API calls (dedup by request id), compactions, tool uses and result sizes, in line order."""
    files = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
        if not recent(path, since):
            continue
        f = {"sub": f"{os.sep}subagents{os.sep}" in path, "sid": None, "cwd": None, "calls": {}, "compacts": [],
             "uses": {}, "results": {}}
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or not ts_ok(d.get("timestamp", ""), since):
                    continue
                f["sid"] = f["sid"] or d.get("sessionId")
                f["cwd"] = f["cwd"] or d.get("cwd")
                if d.get("subtype") == "compact_boundary":
                    m = d.get("compactMetadata") or {}
                    f["compacts"].append((m.get("preTokens"), m.get("postTokens"), len(f["calls"])))
                    continue
                m = d.get("message") or {}
                if d.get("type") == "assistant" and m.get("usage") and m.get("model") not in SKIP_MODELS:
                    rid = d.get("requestId") or m.get("id")
                    c = f["calls"].setdefault(rid, {"model": m.get("model"), "side": bool(d.get("isSidechain"))})
                    c["u"] = m["usage"]  # last block wins (R-claude-dedup)
                for b in m.get("content") if isinstance(m.get("content"), list) else []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and b.get("id"):
                        f["uses"][b["id"]] = (b.get("name") or "", b.get("input") or {})  # repeated lines collapse
                    elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                        f["results"][b["tool_use_id"]] = tokens(b.get("content"))
        if f["sid"]:
            files.append(f)
    return files


def ctx(u):
    """X-ctx: context sent on one call = uncached input + cache read + cache write."""
    return (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)


def curve(xs):
    """X-curve: downsample to CURVE_POINTS evenly spaced turns (first and last kept)."""
    if len(xs) <= CURVE_POINTS:
        return xs
    return [xs[round(i * (len(xs) - 1) / (CURVE_POINTS - 1))] for i in range(CURVE_POINTS)]


def build(files, prices=None):
    prices = prices or load_prices()
    S = {}
    tool_tok, tool_calls, by_turn = {}, {}, {}
    for f in files:
        s = S.setdefault(f["sid"], {"session_id": f["sid"], "project": project(f["cwd"]), "ctx": [], "compactions": [],
                                    "input": 0, "cache_read": 0, "cache_write": 0, "cache_write_cost": 0.0, "cost": 0.0,
                                    "reread_count": 0, "reread_tokens": 0})
        for c in f["calls"].values():
            u, cc = c["u"], c["u"].get("cache_creation") or {}
            t = make_tokens(input=u.get("input_tokens"), output=u.get("output_tokens"),
                            cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"),
                            cache_write_5m=cc.get("ephemeral_5m_input_tokens"), cache_write_1h=cc.get("ephemeral_1h_input_tokens"))
            cost, _ = event_cost(t, c["model"], prices)
            for k in ("input", "cache_read", "cache_write"):
                s[k] += t[k]
            s["cache_write_cost"] += cost["cache_write"]
            s["cost"] += cost["total"]
            if not f["sub"] and not c["side"]:
                s["ctx"].append(ctx(u))  # X-ctx: main thread only; subagents have their own context
        main = [ctx(c["u"]) for c in f["calls"].values()] if not f["sub"] else []
        for pre, post, i in f["compacts"]:  # X-compact: metadata, else the calls around the boundary
            pre = pre if pre is not None else (main[i - 1] if 0 < i <= len(main) else None)
            post = post if post is not None else (main[i] if i < len(main) else None)
            s["compactions"].append([pre, post])
        seen = {}
        for uid, (name, inp) in f["uses"].items():
            rt = f["results"].get(uid, 0)
            tool_tok[name] = tool_tok.get(name, 0) + rt
            tool_calls[name] = tool_calls.get(name, 0) + 1
            path = inp.get("file_path") or inp.get("notebook_path") if isinstance(inp, dict) else None
            if name in EDIT_TOOLS and path:
                seen = {k: v for k, v in seen.items() if k[0] != path}
            elif name == READ_TOOL and path:  # X-reread: identical read (path, offset, limit) in the same thread
                key = (path, inp.get("offset"), inp.get("limit"))
                if key in seen:
                    s["reread_count"] += 1
                    s["reread_tokens"] += rt
                seen[key] = True
    sess = []
    for s in S.values():
        if not s["ctx"] and not s["input"] + s["cache_read"] + s["cache_write"]:
            continue
        for t in CURVE_TURNS:
            if t <= len(s["ctx"]):
                by_turn.setdefault(t, []).append(s["ctx"][t - 1])
        s.update(turns=len(s["ctx"]), peak_ctx=max(s["ctx"], default=0), curve=curve(s.pop("ctx")),
                 cache_write_cost=round(s["cache_write_cost"], 4), cost=round(s["cost"], 4))
        sess.append(s)
    return summarize(sess, tool_tok, tool_calls, by_turn)


def summarize(sess, tool_tok, tool_calls, by_turn):
    n = len(sess)
    peaks = sorted(s["peak_ctx"] for s in sess)
    tot = {k: sum(s[k] for s in sess) for k in ("input", "cache_read", "cache_write", "cache_write_cost", "cost",
                                                "reread_count", "reread_tokens")}
    sent = tot["input"] + tot["cache_read"] + tot["cache_write"]
    comp = [c for s in sess for c in s["compactions"]]
    top = sorted(tool_tok, key=lambda k: (-tool_tok[k], k))[:TOP_TOOLS]
    agg = {
        "sessions": n, "turns": sum(s["turns"] for s in sess),
        "peak_ctx_p50": int(statistics.median(peaks)) if peaks else 0, "peak_ctx_max": peaks[-1] if peaks else 0,
        **{f"over_{t // 1000}k": sum(p >= t for p in peaks) for t in THRESHOLDS},
        "compactions": len(comp), "sessions_compacted": sum(bool(s["compactions"]) for s in sess),
        "compact_pre_p50": _med([c[0] for c in comp]), "compact_post_p50": _med([c[1] for c in comp]),
        "input_share": {k: round(tot[k] / sent, 4) if sent else None for k in ("cache_read", "cache_write", "input")},
        "cache_write_cost": round(tot["cache_write_cost"], 2), "cost": round(tot["cost"], 2),
        "reread_count": tot["reread_count"], "reread_tokens": tot["reread_tokens"],
        "tools_by_result_tokens": [{"tool": k, "result_tokens": tool_tok[k], "calls": tool_calls[k]} for k in top],
    }
    return {"v": 1, "harness": HARNESS, "aggregate": agg, "readout": readout(agg),
            "sessions": sorted(sess, key=lambda s: (-s["peak_ctx"], s["session_id"]))[:TOP_SESSIONS],
            "curve_median": {str(t): int(statistics.median(v)) for t, v in sorted(by_turn.items())}}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else None


def readout(a):
    """X-readout: decision numbers + up to 3 facts, under MAX_READOUT_BYTES as compact JSON."""
    k = lambda x: f"{x / 1000:.0f}k"
    cw_share = a["cache_write_cost"] / a["cost"] if a["cost"] else 0
    facts = []
    if a["over_150k"]:
        facts.append(f"{a['over_150k']}/{a['sessions']} sessions peaked >150k ctx (max {k(a['peak_ctx_max'])})")
    if a["cost"]:
        facts.append(f"cache writes ${a['cache_write_cost']:.0f} = {cw_share:.0%} of est. cost")
    if a["tools_by_result_tokens"]:
        t = a["tools_by_result_tokens"][0]
        facts.append(f"{t['tool']} outputs largest: {k(t['result_tokens'])} tok; re-reads {k(a['reread_tokens'])} tok")
    r = {"sessions": a["sessions"], "peak_p50": a["peak_ctx_p50"], "over_150k": a["over_150k"],
         "over_250k": a["over_250k"], "compactions": a["compactions"],
         "cache_read_share": a["input_share"]["cache_read"], "cache_write_usd": a["cache_write_cost"],
         "reread_tok": a["reread_tokens"], "findings": facts, "detail": OUT}
    while len(json.dumps(r, separators=(",", ":"))) >= MAX_READOUT_BYTES and r["findings"]:
        r["findings"] = r["findings"][:-1]
    return r


def run(root, since):
    return build(scan(os.path.expanduser(root), since))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--root", help=f"transcripts dir (default: config readers.paths.claude-code, else {ROOT})")
    ap.add_argument("--config")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config(a.config)
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=a.days)
    res = run(a.root or cfg["readers"]["paths"].get(HARNESS) or ROOT, since)
    out = a.out or data_dir(cfg)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, OUT), "w") as f:
        json.dump(res, f, indent=1)
    print("context: " + "; ".join(res["readout"]["findings"] or ["no data"]) + f" -> {os.path.join(out, OUT)}")


if __name__ == "__main__":
    main()
