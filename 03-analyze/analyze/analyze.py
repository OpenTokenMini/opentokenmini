"""analyze: events/*.jsonl -> sessions.jsonl + analysis.json. Specs (M-*, O-*): analyze/METHOD.md.

python3 03-analyze/analyze/analyze.py [EVENTS_DIR] [--out DIR] [--days N] [--harness ID] [--config PATH] [--now ISO]
"""
import argparse, json, math, os, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector
from schemas.cost import worst_basis, zero_tokens, zero_cost, CACHE_TTL
import importlib.util


def _load(name):  # by path, unique module name: every stage has a connectors.py
    spec = importlib.util.spec_from_file_location("analyze_" + name, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


connectors, outliers = _load("connectors"), _load("outliers")

DEDUP_SLACK_S = 60          # M-dedup: window slack around preferred-source events, seconds
IDLE_CAP_S = 300            # M-session: gaps longer than this count as this many seconds of activity
P90 = 0.9                   # M-session-cost-p90 rank
MIN_GROUP = 20             # O-model-group: fewer sessions with one main model -> scored against the harness baseline
MIN_CALLS_RATIO = 3         # O-robust-z: sessions with fewer calls are left out of per-call/per-turn/cache ratios
TOP_SESSIONS = 5            # metrics[].session_ids length
HUMAN_SOURCES = ("user",)   # M-human-decision-share: decision_source values that mean a person decided
CATALOG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics.json")))
CAT = {m["id"]: m for m in CATALOG["metrics"]}
COST_KEYS = ("input", "output", "cache_read", "cache_write", "total")
TOK_KEYS = ("input", "output", "cache_read", "cache_write", "reasoning")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond // 1000:03d}" if dt.microsecond else "") + "Z"


def div(a, b):
    return a / b if b else None


def add(acc, part, keys):
    for k in keys:
        acc[k] += part[k]


# ---------- M-dedup ----------
def dedup(events, prefer):
    """M-dedup. events sorted. Returns (kept, dropped_by_harness)."""
    seen, kept1 = set(), []
    for e in events:                                   # rule 1: same source, same request id
        key = (e["source"], e["harness"], e["request_id"])
        if e["request_id"] is not None:
            if key in seen:
                continue
            seen.add(key)
        kept1.append(e)
    pref_ids, win, has_ids = {}, {}, defaultdict(bool)
    for e in kept1:
        if e["source"] != prefer:
            continue
        k = (e["harness"], e["session_id"], e["kind"])
        if e["request_id"] is not None:
            pref_ids.setdefault((e["harness"], e["request_id"]), e)
            has_ids[k] = True
        lo, hi = win.get(k, (e["_t"], e["_t"]))
        win[k] = (min(lo, e["_t"]), max(hi, e["_t"]))
    kept, dropped = [], Counter()
    for e in kept1:
        if e["source"] != prefer:
            k = (e["harness"], e["session_id"], e["kind"])
            if e["request_id"] is not None and (e["harness"], e["request_id"]) in pref_ids:   # rule 2
                merge_ttl(pref_ids[(e["harness"], e["request_id"])], e)
                dropped[e["harness"]] += 1
                continue
            if k in win and (e["request_id"] is None or not has_ids[k]):                       # rule 3
                lo, hi = win[k]
                if lo - DEDUP_SLACK_S <= e["_t"] <= hi + DEDUP_SLACK_S:
                    dropped[e["harness"]] += 1
                    continue
        kept.append(e)
    dropped.update({e["harness"]: 0 for e in events})
    return kept, dropped


def merge_ttl(keep, other):
    """M-dedup-ttl: the kept event takes tokens/cost/basis from its duplicate when only the duplicate has the
    cache-write TTL split (claude transcript vs otel); identity, duration and the rest stay."""
    if any(k in other["tokens"] for k in CACHE_TTL) and not any(k in keep["tokens"] for k in CACHE_TTL):
        keep.update(tokens=dict(other["tokens"]), cost=dict(other["cost"]), cost_basis=other["cost_basis"])
        keep.pop("cache_split", None)


# ---------- M-session ----------
def build_session(evs):
    first = lambda f: next((e[f] for e in evs if e[f] is not None), None)
    s = {"v": 1, "session_id": evs[0]["session_id"], "harness": evs[0]["harness"],
         "project": first("project") or "", "repo": first("repo"), "user": first("user"),
         "start": fmt_ts(evs[0]["_t_dt"]), "end": fmt_ts(evs[-1]["_t_dt"]),
         "active_minutes": round(sum(min(b["_t"] - a["_t"], IDLE_CAP_S) for a, b in zip(evs, evs[1:])) / 60, 4),
         "calls": 0, "turns": 0, "errors": 0, "retries": 0, "subagent_cost": 0.0,
         "tokens": zero_tokens(), "cost": zero_cost(), "cost_basis": "unknown",
         "models": {}, "tools": {}, "mcp": {}, "sources": sorted({e["source"] for e in evs})}
    bases, call_tools = [], {t for e in evs if e["kind"] == "api_call" for t in e["tools"]}
    for e in evs:
        if e["kind"] == "user_prompt":
            s["turns"] += 1
        if e["kind"] == "api_call":
            s["calls"] += 1
            s["errors"] += e["error"] is not None
            s["retries"] += e["retries"]
            add(s["tokens"], e["tokens"], TOK_KEYS)
            add(s["cost"], e["cost"], COST_KEYS)
            if e["subagent"]:
                s["subagent_cost"] += e["cost"]["total"]
            m = e["model"] or "unknown"
            s["models"][m] = s["models"].get(m, 0.0) + e["cost"]["total"]
            bases.append(e["cost_basis"])
            for t in e["tools"]:
                s["tools"][t] = s["tools"].get(t, 0) + 1
        names = e["tools"] if e["kind"] == "api_call" else [e["tool"]] if e["kind"] == "tool_decision" and e["tool"] else []
        if e["kind"] == "tool_decision" and e["tool"] in call_tools:
            names = []                                 # already counted from the api_call (M-mcp)
        for t in names:
            if t.startswith("mcp__"):
                srv = s["mcp"].setdefault(t.split("__")[1], {"calls": 0, "errors": 0})
                srv["calls"] += 1
                srv["errors"] += e["error"] is not None
    s["cost_basis"] = worst_basis(bases)
    return s


# ---------- M-* group metrics ----------
def group_values(ss, evs):
    """All scope=group metric values for one group: (sessions, their events)."""
    t, c = zero_tokens(), zero_cost()
    for s in ss:
        add(t, s["tokens"], TOK_KEYS)
        add(c, s["cost"], COST_KEYS)
    calls, turns = sum(s["calls"] for s in ss), sum(s["turns"] for s in ss)
    models = Counter()
    for s in ss:
        models.update(s["models"])
    sc = sorted(s["cost"]["total"] for s in ss if s["calls"])
    mcp_calls = sum(v["calls"] for s in ss for v in s["mcp"].values())
    mcp_err = sum(v["errors"] for s in ss for v in s["mcp"].values())
    dec = [e for e in evs if e["kind"] == "tool_decision"]
    return {
        "M-spend": c["total"],
        "M-cost-share-input": div(c["input"], c["total"]),
        "M-cost-share-output": div(c["output"], c["total"]),
        "M-cost-share-cache-read": div(c["cache_read"], c["total"]),
        "M-cost-share-cache-write": div(c["cache_write"], c["total"]),
        "M-cache-hit-rate": div(t["cache_read"], t["input"] + t["cache_read"] + t["cache_write"]),
        "M-cost-per-call": div(c["total"], calls),
        "M-calls-per-turn": div(calls, turns),
        "M-subagent-share": div(sum(s["subagent_cost"] for s in ss), c["total"]),
        "M-top-model-share": div(max(models.values(), default=0.0), c["total"]),
        "M-session-cost-median": statistics.median(sc) if sc else None,
        "M-session-cost-p90": sc[math.ceil(P90 * len(sc)) - 1] if sc else None,
        "M-error-rate": div(sum(s["errors"] for s in ss), calls),
        "M-retries-per-call": div(sum(s["retries"] for s in ss), calls),
        "M-mcp-error-rate": div(mcp_err, mcp_calls),
        "M-approval-rate": div(sum(e["decision"] == "accept" for e in dec), len(dec)),
        "M-human-decision-share": div(sum(e["decision_source"] in HUMAN_SOURCES for e in dec), len(dec)),
    }


def session_values(s):
    """scope=session metrics (O-robust-z inputs); None = session left out."""
    ok = s["calls"] >= MIN_CALLS_RATIO
    t = s["tokens"]
    return {
        "M-session-cost": s["cost"]["total"] if s["calls"] else None,
        "M-session-cost-per-call": div(s["cost"]["total"], s["calls"]) if ok else None,
        "M-session-calls-per-turn": div(s["calls"], s["turns"]) if ok else None,
        "M-session-cache-hit-rate": div(t["cache_read"], t["input"] + t["cache_read"] + t["cache_write"]) if ok else None,
    }


def top_ids(ss):
    return [s["session_id"] for s in sorted(ss, key=lambda s: (-s["cost"]["total"], s["session_id"]))[:TOP_SESSIONS]]


def rows(ss, key_fn):
    """M-by-dim rows: name, cost, sessions, calls; cost desc then name."""
    acc = defaultdict(lambda: [0.0, set(), 0])
    for s in ss:
        for name, cost, calls in key_fn(s):
            a = acc[name]
            a[0] += cost
            a[1].add(s["session_id"])
            a[2] += calls
    return [{"name": k, "cost": v[0], "sessions": len(v[1]), "calls": v[2]}
            for k, v in sorted(acc.items(), key=lambda kv: (-kv[1][0], kv[0]))]


# ---------- stages ----------
def select_events(raw, since, now, harness):
    """M-filter, then the canonical sort every sum follows."""
    evs = []
    for i, e in enumerate(raw):
        if harness and e.get("harness") != harness:
            continue
        dt = parse_ts(e["ts"])
        if since and not (since <= dt <= now):
            continue
        evs.append(dict(e, _t_dt=dt, _t=dt.timestamp(), _i=i))
    evs.sort(key=lambda e: (e["_t"], e["harness"], e["session_id"], e["source"], e["request_id"] or "", e["_i"]))
    return evs


def build_sessions(kept):
    """M-session. Returns (sessions sorted by harness/start/id, {(harness, session_id): events})."""
    by_sess = defaultdict(list)
    for e in kept:
        by_sess[(e["harness"], e["session_id"])].append(e)
    sessions = sorted((build_session(v) for v in by_sess.values()),
                      key=lambda s: (s["harness"], s["start"], s["session_id"]))
    return sessions, by_sess


def group_metrics(sessions, sess_ev, harnesses):
    """scope=group metrics for all sessions and per harness. Returns (metric rows, {group: values})."""
    groups = [(None, None, sessions)] + [("harness", h, [s for s in sessions if s["harness"] == h]) for h in harnesses]
    metrics, values = [], {}
    for gb, g, ss in groups:
        vals = group_values(ss, [e for s in ss for e in sess_ev[(s["harness"], s["session_id"])]])
        values[g] = vals
        for mid, v in vals.items():
            m = CAT[mid]
            metrics.append({"id": mid, "name": m["name"], "definition": m["definition"], "value": v,
                            "unit": m["unit"], "group_by": gb, "group": g, "n": len(ss), "session_ids": top_ids(ss)})
    return metrics, values


def main_model(s):
    """O-model-group: the model with the most cost in the session (name breaks ties)."""
    return min(s["models"].items(), key=lambda kv: (-kv[1], kv[0]))[0] if s["models"] else "unknown"


def find_outliers(sessions, harnesses):
    """O-robust-z per (harness, main model); groups under MIN_GROUP sessions use the harness baseline."""
    found = []
    for h in harnesses:
        sv = [(s["session_id"], main_model(s), session_values(s)) for s in sessions if s["harness"] == h]
        for mid in (m["id"] for m in CATALOG["metrics"] if m["scope"] == "session"):
            log, floor = CAT[mid].get("scale") == "log", bool(CAT[mid].get("spread_floor"))
            items = [(sid, m, v[mid]) for sid, m, v in sv if v[mid] is not None and (v[mid] > 0 or not log)]
            by_model, small, out = defaultdict(list), set(), []
            for sid, m, v in items:
                by_model[m].append((sid, v))
            for m, it in sorted(by_model.items()):
                if len(it) >= MIN_GROUP:
                    out += outliers.find(mid, f"{h}/{m}", it, log=log, floor=floor)
                else:
                    small.update(sid for sid, _ in it)
            if small:
                out += [o for o in outliers.find(mid, h, [(sid, v) for sid, _, v in items], log=log, floor=floor)
                        if o["session_id"] in small]
            found += sorted(out, key=lambda o: (-abs(o["score"]), o["session_id"]))
    return found


def recommendations(harnesses, values):
    """M-recommendation-evidence."""
    recs = []
    for h in harnesses:
        for r in CATALOG["recommendations"]:
            ev = [{"metric": mid, "value": values[h][mid]} for mid in r["evidence"]]
            if all(x["value"] is None for x in ev):
                continue
            recs.append({"id": f"{r['id']}/{h}", "candidate": r["candidate"], "harness": h,
                         "evidence": ev, "p_yes": None, "verdict": None})
    return recs


def totals_of(sessions):
    totals = {"cost": zero_cost(), "tokens": zero_tokens(), "calls": 0, "sessions": len(sessions), "turns": 0,
              "projects": len({s["project"] for s in sessions}), "subagent_cost": 0.0}
    for s in sessions:
        add(totals["cost"], s["cost"], COST_KEYS)
        add(totals["tokens"], s["tokens"], TOK_KEYS)
        totals["calls"] += s["calls"]
        totals["turns"] += s["turns"]
        totals["subagent_cost"] += s["subagent_cost"]
    return totals


def coverage_of(enabled, harnesses, kept, sessions, dropped):
    """M-coverage, one entry per enabled or seen harness."""
    coverage = {}
    for h in sorted(set(enabled) | set(harnesses)):
        he = [e for e in kept if e["harness"] == h]
        calls = [e for e in he if e["kind"] == "api_call"]
        bc = Counter(e["cost_basis"] for e in calls)
        c = {"events": len(he), "sessions": sum(s["harness"] == h for s in sessions),
             "first_ts": fmt_ts(he[0]["_t_dt"]) if he else None, "last_ts": fmt_ts(he[-1]["_t_dt"]) if he else None,
             "sources": sorted({e["source"] for e in he}),
             "cost_basis_share": {b: n / len(calls) for b, n in sorted(bc.items())},
             "unpriced_calls": bc.get("unknown", 0), "duplicates_dropped": dropped.get(h, 0)}
        if not he:
            c["reason"] = "no events"
        coverage[h] = c
    return coverage


def breakdowns(kept, sessions):
    """M-by-day, M-by-dim, M-tool-cost, mcp."""
    day = defaultdict(lambda: defaultdict(float))
    tool = defaultdict(lambda: [0.0, 0])
    model_calls = defaultdict(Counter)
    for e in (e for e in kept if e["kind"] == "api_call"):
        day[e["_t_dt"].strftime("%Y-%m-%d")][e["harness"]] += e["cost"]["total"]
        for t in e["tools"]:
            tool[t][0] += e["cost"]["total"] / len(e["tools"])
            tool[t][1] += 1
        model_calls[(e["harness"], e["session_id"])][e["model"] or "unknown"] += 1
    mcp = defaultdict(lambda: [0, 0])
    for s in sessions:
        for srv, v in s["mcp"].items():
            mcp[srv][0] += v["calls"]
            mcp[srv][1] += v["errors"]
    return {"day": [dict({"day": d}, **dict(sorted(v.items()))) for d, v in sorted(day.items())],
            "harness": rows(sessions, lambda s: [(s["harness"], s["cost"]["total"], s["calls"])]),
            "model": rows(sessions, lambda s: [(m, c, model_calls[(s["harness"], s["session_id"])][m])
                                               for m, c in s["models"].items()]),
            "project": rows(sessions, lambda s: [(s["project"], s["cost"]["total"], s["calls"])]),
            "tool": [{"name": k, "cost": v[0], "calls": v[1]} for k, v in sorted(tool.items(), key=lambda kv: (-kv[1][0], kv[0]))],
            "mcp": [{"server": k, "calls": v[0], "errors": v[1], "error_rate": div(v[1], v[0])} for k, v in sorted(mcp.items())]}


def period_of(since, now, days, kept):
    if since:
        return {"from": fmt_ts(since), "to": fmt_ts(now), "days": days}
    if kept:
        return {"from": fmt_ts(kept[0]["_t_dt"]), "to": fmt_ts(kept[-1]["_t_dt"]),
                "days": round((kept[-1]["_t"] - kept[0]["_t"]) / 86400, 4)}
    return {"from": fmt_ts(now), "to": fmt_ts(now), "days": 0}


# ---------- main ----------
def analyze(raw, cfg, days=None, harness=None, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days) if days is not None else None
    kept, dropped = dedup(select_events(raw, since, now, harness), cfg["analyze"]["prefer_source"])
    sessions, sess_ev = build_sessions(kept)
    harnesses = sorted({s["harness"] for s in sessions})
    metrics, values = group_metrics(sessions, sess_ev, harnesses)
    enabled = [harness] if harness else cfg["readers"]["enabled"]
    filters = {k: v for k, v in (("days", days), ("harness", harness)) if v is not None}
    analysis = {"v": 1, "generated": fmt_ts(now), "period": period_of(since, now, days, kept), "filters": filters,
                "totals": totals_of(sessions), "coverage": coverage_of(enabled, harnesses, kept, sessions, dropped),
                "by": breakdowns(kept, sessions), "metrics": metrics, "outliers": find_outliers(sessions, harnesses),
                "recommendations": recommendations(harnesses, values)}
    return sessions, analysis


def main(argv=None):
    p = argparse.ArgumentParser(description="events -> sessions.jsonl + analysis.json")
    p.add_argument("events_dir", nargs="?")
    p.add_argument("--out")
    p.add_argument("--days", type=float)
    p.add_argument("--harness")
    p.add_argument("--config")
    p.add_argument("--now", help="ISO UTC 'now' for --days and generated (reproducible runs)")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    root = data_dir(cfg) if not (a.events_dir and a.out) else None
    cfg["analyze"]["_events_dir"] = a.events_dir or os.path.join(root, "events")
    cfg["analyze"]["_out_dir"] = a.out or root
    load = connector(connectors.SOURCES, cfg["analyze"]["source"], "analyze.source")
    write = connector(connectors.SINKS, cfg["analyze"]["sink"], "analyze.sink")
    days = int(a.days) if a.days is not None and a.days == int(a.days) else a.days
    sessions, analysis = analyze(load(cfg), cfg, days, a.harness, parse_ts(a.now) if a.now else None)
    write(sessions, analysis, cfg)
    t = analysis["totals"]
    print(f"analyze: {t['sessions']} sessions, {t['calls']} calls, ${t['cost']['total']:.2f}, "
          f"{sum(o['flagged'] for o in analysis['outliers'])} outliers", file=sys.stderr)


if __name__ == "__main__":
    main()
