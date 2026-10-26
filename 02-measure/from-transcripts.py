#!/usr/bin/env python3
"""Summarizes local coding-agent session logs into usage JSON: cost, tokens, models, projects, tools, turns.
Thin wrapper over the transcript readers (readers/, one file per vendor) and schemas/prices.json; same output
shape as the old script (todelete/from-transcripts.py), read by 00-docs/demo/.
Reads only metadata (usage, model, tool names, folder, timestamps); prompts, replies and code are never copied.
Usage: python3 02-measure/from-transcripts.py [days] > usage.json"""
import collections, json, os, sys, time
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path[:0] = [str(REPO / "02-measure" / "readers"), str(REPO / "02-measure")]
import readers  # noqa: E402  (02-measure/readers/readers.py)
from schemas.config import load_config  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
TOP = 12  # rows kept per ranking
BIG_CTX = 150_000  # tokens of context per call counted as "large" in totals.big_context_cost
TOKEN_NAMES = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
               "cache_write": "cache_creation_input_tokens"}  # old output names


def main():
    cfg = load_config(None)
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    events, summary = readers.run(cfg["readers"]["enabled"], since, cfg)
    for h, s in summary.items():
        if s["error"]:  # one harness changing its format must not hide the others
            print(f"{h}: skipped, {s['error']}", file=sys.stderr)
    by_day = collections.defaultdict(collections.Counter)
    models, tools, tool_calls, tok, prompts, cost_type = (collections.Counter() for _ in range(6))
    big_ctx = 0  # cost of calls whose context exceeded BIG_CTX tokens
    harness = collections.defaultdict(lambda: {"cost": 0, "calls": 0, "sessions": set()})
    proj = collections.defaultdict(lambda: {"cost": 0, "calls": 0, "sessions": set(), "harnesses": set()})
    sess = collections.defaultdict(lambda: {"cost": 0, "calls": 0, "project": "", "day": "", "sub": 0, "harness": "",
                                            "ctx": 0, "ctx_sum": 0, "models": collections.Counter()})
    calls = 0
    for e in events:
        if e["kind"] == "user_prompt":
            prompts[e["session_id"]] += 1
            continue
        if e["kind"] != "api_call":
            continue
        calls += 1
        usd, model, day = e["cost"]["total"], (e["model"] or "?").removeprefix("claude-"), e["ts"][:10]
        by_day[day][model] += usd
        models[model] += usd
        for t in e["tools"] or ["(reply)"]:
            tools[t] += usd / max(1, len(e["tools"]))
            tool_calls[t] += 1
        h = harness[e["harness"]]
        h["cost"] += usd; h["calls"] += 1; h["sessions"].add(e["session_id"])
        p = proj[e["project"]]
        p["cost"] += usd; p["calls"] += 1; p["sessions"].add(e["session_id"]); p["harnesses"].add(e["harness"])
        s = sess[e["session_id"]]
        s["cost"] += usd; s["calls"] += 1; s["project"] = e["project"]; s["day"] = min(s["day"] or day, day)
        s["sub"] += usd if e["subagent"] else 0; s["harness"] = e["harness"]
        ctx = sum(e["tokens"][k] for k in ("input", "cache_read", "cache_write"))  # context sent on this call
        s["ctx"] = max(s["ctx"], ctx); s["ctx_sum"] += ctx; s["models"][model] += usd
        big_ctx += usd if ctx > BIG_CTX else 0
        cost_type.update({k: e["cost"].get(k) or 0 for k in TOKEN_NAMES})
        tok.update({TOKEN_NAMES[k]: e["tokens"][k] + (e["tokens"]["reasoning"] if k == "output" else 0) for k in TOKEN_NAMES})
    for sid, s in sess.items():
        s["turns"] = prompts.get(sid, 0)
    json.dump({
        "generated": time.strftime("%Y-%m-%d"), "days": DAYS,
        "prices": "logged cost where the harness records one, else list price, see 02-measure/schemas/prices.json",
        "totals": {"cost": round(sum(models.values()), 2), "calls": calls, "sessions": len(sess),
                   "turns": sum(prompts.values()), "projects": len(proj),
                   "subagent_cost": round(sum(s["sub"] for s in sess.values()), 2),
                   "cost_by_type": {k: round(v, 2) for k, v in cost_type.items()},
                   "big_context": BIG_CTX, "big_context_cost": round(big_ctx, 2)},
        "harnesses": {k: {"cost": round(v["cost"], 2), "calls": v["calls"], "sessions": len(v["sessions"])}
                      for k, v in sorted(harness.items(), key=lambda x: -x[1]["cost"])},
        "tokens": dict(tok),
        "by_day": [{"day": d, **{k: round(v, 2) for k, v in by_day[d].items()}} for d in sorted(by_day)],
        "models": {k: round(v, 2) for k, v in models.most_common()},
        "projects": [{"name": k, "cost": round(v["cost"], 2), "calls": v["calls"], "sessions": len(v["sessions"]),
                      "harnesses": sorted(v["harnesses"])}
                     for k, v in sorted(proj.items(), key=lambda x: -x[1]["cost"])][:TOP],
        "tools": [{"name": k, "cost": round(v, 2), "calls": tool_calls[k]} for k, v in tools.most_common(TOP)],
        "sessions": sorted(({"cost": round(s["cost"], 2), "calls": s["calls"], "turns": s["turns"], "harness": s["harness"],
                             "project": s["project"], "day": s["day"], "subagent_cost": round(s["sub"], 2),
                             "ctx_max": s["ctx"], "ctx_avg": round(s["ctx_sum"] / s["calls"]),
                             "model": s["models"].most_common(1)[0][0]}
                            for s in sess.values()), key=lambda s: -s["cost"]),
    }, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
