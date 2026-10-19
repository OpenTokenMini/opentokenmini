"""Builds decision items (METHOD.md D-*) from analysis.json, sessions.jsonl and impact.jsonl.
An item: {point, subject, harness, facts, state, question, options, kind, agent}. No vendor calls here."""
import hashlib, json, os, sys
import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.cost import load_prices, price_for

MAX_STATE_CHARS = 6000  # D-state: ~1.5k tokens, under the 2k budget per call
TOP_TOOLS = 5  # tools listed in a state
TOP_MODELS = 3  # models listed in a state
CATALOG = str(REPO / "03-analyze" / "analyze" / "metrics.json")  # D-recommendation candidates (single source)
PRICE_TIERS = ((1.0, "budget"), (15.0, "standard"))  # D-outlier-model: output USD/Mtok upper bounds, above = premium
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch", "edit", "write")  # D-commit-link evidence


def share(part, total):
    return round(part / total, 3) if total else 0.0


def cost_mix(cost):  # D-state: per-type cost shares
    return {k: share(cost.get(k, 0), cost.get("total", 0)) for k in ("input", "output", "cache_read", "cache_write")}


def top(d, n):
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:n])


def session_facts(s):
    c, calls, turns = s["cost"], s["calls"], s["turns"]
    return {"harness": s["harness"], "cost_usd": round(c["total"], 4), "cost_mix": cost_mix(c),
            "turns": turns, "calls": calls, "calls_per_turn": round(calls / turns, 2) if turns else None,
            "cost_per_call": round(c["total"] / calls, 5) if calls else None,
            "subagent_share": share(s.get("subagent_cost", 0), c["total"]), "errors": s["errors"], "retries": s["retries"],
            "active_minutes": s["active_minutes"], "cache_hit_rate": cache_hit(s["tokens"]),
            "models_cost_usd": {m: round(v, 4) for m, v in top(s.get("models", {}), TOP_MODELS).items()},
            "top_tools_calls": top(s.get("tools", {}), TOP_TOOLS)}


def cache_hit(t):  # same definition as analyze M-cache-hit-rate
    den = t["input"] + t["cache_read"] + t["cache_write"]
    return round(t["cache_read"] / den, 3) if den else None


def harness_facts(rows, name):
    cost = {k: sum(s["cost"][k] for s in rows) for k in ("input", "output", "cache_read", "cache_write", "total")}
    tok = {k: sum(s["tokens"][k] for s in rows) for k in ("input", "output", "cache_read", "cache_write", "reasoning")}
    calls, turns = sum(s["calls"] for s in rows), sum(s["turns"] for s in rows)
    models, mcp = {}, {}
    for s in rows:
        for m, v in s.get("models", {}).items():
            models[m] = models.get(m, 0) + v
        for srv, x in s.get("mcp", {}).items():
            a = mcp.setdefault(srv, [0, 0])
            a[0] += x["calls"]; a[1] += x["errors"]
    costs = sorted(s["cost"]["total"] for s in rows)
    return {"harness": name, "sessions": len(rows), "cost_usd": round(cost["total"], 4),
            "cost_mix": cost_mix(cost), "cache_hit_rate": cache_hit(tok), "turns": turns, "calls": calls,
            "calls_per_turn": round(calls / turns, 2) if turns else None,
            "median_session_cost": round(costs[len(costs) // 2], 4),
            "subagent_share": share(sum(s.get("subagent_cost", 0) for s in rows), cost["total"]),
            "model_cost_share": {m: share(v, cost["total"]) for m, v in top(models, TOP_MODELS).items()},
            "mcp_error_rate": {k: share(e, c) for k, (c, e) in sorted(mcp.items(), key=lambda kv: -kv[1][0])[:TOP_TOOLS]}}


def state_text(intro, facts):  # D-state
    return (intro + " " + json.dumps(facts, separators=(",", ":"), sort_keys=True))[:MAX_STATE_CHARS]


def item(point, subject, harness, intro, facts, spec, agent="decide", **fmt):
    return {"point": point, "subject": subject, "harness": harness, "facts": facts, "state": state_text(intro, facts), "question": spec["question"].format(**fmt),
            "options": spec["options"], "kind": spec["kind"], "agent": agent}


def price_tier(model, prices):  # D-outlier-model
    p = price_for(model, prices)
    if not p:
        return None, "unpriced"
    return {"input": p["input"], "output": p["output"]}, next((t for lim, t in PRICE_TIERS if p["output"] <= lim), "premium")


def main_model(s):
    return max(s["models"].items(), key=lambda kv: kv[1])[0] if s.get("models") else None


def baseline_models(by_sid):  # D-outlier-model: most common main model per harness (what a fallback median reflects)
    n = {}
    for s in by_sid.values():
        m = main_model(s)
        if m:
            n.setdefault(s["harness"], {}).setdefault(m, 0)
            n[s["harness"]][m] += 1
    return {h: max(c.items(), key=lambda kv: kv[1])[0] for h, c in n.items()}


def model_facts(o, s, prices, base):  # D-outlier-model: main model, list price tier, baseline kind
    f = {"baseline": "model" if "/" in o["group"] else "harness_fallback"}
    if f["baseline"] == "harness_fallback" and o["group"] in base:
        f["baseline_typical_model"] = base[o["group"]]
        f["baseline_typical_model_price_tier"] = price_tier(base[o["group"]], prices)[1]
    if s and s.get("models"):
        m = main_model(s)
        f["main_model"], (f["main_model_list_usd_per_mtok"], f["main_model_price_tier"]) = m, price_tier(m, prices)
    return f


def outliers(analysis, by_sid, spec, prices=None):
    """D-outlier-explanation: one item per outlier in analysis.outliers."""
    prices = load_prices() if prices is None else prices
    base = baseline_models(by_sid)
    defs = {m["id"]: m["definition"] for m in analysis.get("metrics", [])}
    for i, o in enumerate(analysis.get("outliers", [])):
        f = {"metric": o["metric"], "metric_definition": defs.get(o["metric"]), "group": o["group"],
             "value": o["value"], "group_median": o["baseline"], "robust_z": o["score"], "group_n": o["n"]}
        s = by_sid.get(o.get("session_id"))
        f.update(model_facts(o, s, prices, base))
        if s:
            f["session"] = session_facts(s)
        subject = f"{o['metric']}:{o['group']}:{o.get('session_id') or '-'}"
        yield i, item("outlier_explanation", subject, s["harness"] if s else o["group"], "Coding agent usage outlier.", f, spec)


def recommendations(analysis, sessions, spec, harness=None):
    """D-recommendation: analysis.recommendations plus every catalog candidate (analyze/metrics.json), per harness with sessions.
    Dedup by id `<rec id>/<harness>`, the same id analyze writes."""
    groups = {}
    for s in sessions:
        groups.setdefault(s["harness"], []).append(s)
    recs = [(r["id"], r["candidate"], r.get("harness"), r.get("evidence", [])) for r in analysis.get("recommendations", [])]
    seen = {rid for rid, _, _, _ in recs}
    catalog = json.load(open(CATALOG))["recommendations"]
    recs += [(f"{c['id']}/{h}", c["candidate"], h, []) for h in sorted(groups) for c in catalog if f"{c['id']}/{h}" not in seen]
    for rid, cand, h, ev in recs:
        if harness and h != harness:
            continue
        rows = groups.get(h) if h else sessions
        if not rows:
            continue
        f = harness_facts(rows, h or "all")
        if ev:
            f["evidence"] = {e["metric"]: e["value"] for e in ev}
        intro = f"Coding agent usage of harness {h or 'all'} over {analysis['period']['days']} days."
        yield (rid, cand, h), item("recommendation", rid, h, intro, f, spec, candidate=cand)


def link_subject(session_id, shas):
    """D-commit-link subject = impact L-subject: changes when the candidate's commit set changes."""
    return f"{session_id}:{hashlib.sha256(','.join(sorted(shas)).encode()).hexdigest()[:8]}"


def commit_links(impact, by_sid, spec):
    """D-commit-link: one item per impact record with link "window" and link_p null."""
    for r in impact:
        if r["link"] != "window" or r["link_p"] is not None or not r["commits"]:
            continue
        s = by_sid.get(r["session_id"])
        if not s:
            continue
        f = {"session": {"harness": s["harness"], "start": s["start"], "end": s["end"], "active_minutes": s["active_minutes"],
                         "calls": s["calls"], "turns": s["turns"],
                         "edit_tool_calls": sum(v for k, v in s.get("tools", {}).items() if k in EDIT_TOOLS)},
             "commits": [{k: c[k] for k in ("ts", "files", "added", "deleted", "agent_trailer", "on_default_branch")}
                         for c in r["commits"]]}
        subject = link_subject(r["session_id"], [c["sha"] for c in r["commits"]])
        yield subject, item("commit_link", subject, s["harness"],
                                                        "Agent session and nearby commits by the same author.", f, spec,
                                                        agent="impact")
