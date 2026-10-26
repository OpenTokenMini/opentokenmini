#!/usr/bin/env python3
"""Orchestration patterns from Claude Code transcripts: per delegating session, workers, fan-out, cost split, result size.
Specs: ../orchestration.md (O-*).

python3 04-auto-analysis/orchestration/orchestration.py [--days N] [--root DIR] [--config PATH] [--out DIR]
Reads <project>/<session>.jsonl and <project>/<session>/subagents/**/agent-*.jsonl (+ .meta.json), in memory;
writes orchestration.jsonl (one record per delegating session) + orchestration_summary.json (its "readout" goes to readout.json).
"""
import argparse, collections, glob, json, os, re, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir
from schemas.cost import load_prices, make_tokens, event_cost

DAYS = 7
ROOT = "~/.claude/projects"
HARNESS = "claude-code"
AGENT_TOOLS = ("Agent", "Task")       # O-launch: tool names that start a subagent
CHARS_PER_TOKEN = 4                   # O-result: token estimate = characters / 4
HUGE_RESULT_TOKENS = 2000             # O-huge: a worker whose results cost the launcher more than this
ERROR_STATUS = ("failed", "killed", "error", "cancelled")  # O-error: worker end states counted as errors
COMMIT_RX = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")  # O-commit: in a Bash command
NOTE_RX = re.compile(r"<tool-use-id>(\w+)</tool-use-id>.*?<status>(\w+)</status>", re.S)
FAMILY_RX = re.compile(r"opus|sonnet|haiku|fable|gpt|gemini", re.I)
DEEP_DEPTH = 2                        # O-topology: a worker at this spawn depth or deeper
FANOUT_MIN = 3                        # O-topology: workers running at once, or launched in one turn
TOPOLOGIES = [  # O-topology: first matching rule wins
    ("deep", lambda s: s["max_depth"] >= DEEP_DEPTH),
    ("single-helper", lambda s: s["workers"] == 1),
    ("fan-out", lambda s: max(s["max_concurrent"], s["max_batch"]) >= FANOUT_MIN),
    ("serial", lambda s: s["max_concurrent"] <= 1),
    ("small-parallel", lambda s: True),
]
READOUT_BYTES = 400                   # O-readout: compact section limit (findings dropped until it fits)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def iso(d):
    return d.strftime(ISO) if d else None


def tokens(x):
    """O-result: estimated tokens of a tool_result content (str or blocks)."""
    if isinstance(x, str):
        return -(-len(x) // CHARS_PER_TOKEN)
    if isinstance(x, list):
        return sum(tokens(b.get("text", "") if isinstance(b, dict) and "text" in b else json.dumps(b)) for b in x)
    return tokens(json.dumps(x)) if x is not None else 0


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def family(model):
    m = FAMILY_RX.search(model or "")
    return m.group(0).lower() if m else (model or "unknown")


def scan_file(path, prices):
    """O-scan: one transcript -> usage per message id, Agent launches, their results and notifications, commits."""
    f = {"first": None, "last": None, "msgs": {}, "launches": {}, "results": {}, "notes": collections.defaultdict(list),
         "commits": []}
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = ts(d.get("timestamp"))
            if t is None or d.get("type") not in ("user", "assistant", "attachment"):
                continue
            f["first"], f["last"] = min(f["first"] or t, t), max(f["last"] or t, t)
            m = d.get("message") or {}
            u = m.get("usage")
            if d["type"] == "assistant" and u and m.get("id"):  # lines of one message repeat its usage: keep one
                cc = u.get("cache_creation") or {}
                tk = make_tokens(input=u.get("input_tokens"), output=u.get("output_tokens"),
                                 cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"),
                                 cache_write_5m=cc.get("ephemeral_5m_input_tokens"), cache_write_1h=cc.get("ephemeral_1h_input_tokens"))
                f["msgs"][m["id"]] = (m.get("model"), event_cost(tk, m.get("model"), prices)[0]["total"],
                                      tk["input"] + tk["cache_read"] + tk["cache_write"])
            c = m.get("content")
            note = c if isinstance(c, str) else ((d.get("attachment") or {}).get("prompt") or "")
            if isinstance(note, str) and "<task-notification>" in note:  # O-result: async worker hand-back
                for tid, status in NOTE_RX.findall(note):
                    f["notes"][tid].append((tokens(note), status))
            for b in c if isinstance(c, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") in AGENT_TOOLS:
                    f["launches"][b.get("id")] = {"ts": t, "turn": m.get("id") or d.get("uuid")}
                elif b.get("type") == "tool_use" and b.get("name") == "Bash" and \
                        COMMIT_RX.search(str((b.get("input") or {}).get("command", ""))):
                    f["commits"].append(t)
                elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                    r = d.get("toolUseResult")
                    f["results"][b["tool_use_id"]] = (tokens(b.get("content")), bool(b.get("is_error")),
                                                      r.get("status") if isinstance(r, dict) else None)
    return f


def worker_record(path, meta, f):
    models = collections.Counter(mo for mo, _, _ in f["msgs"].values() if mo and mo != "<synthetic>")
    model = models.most_common(1)[0][0] if models else meta.get("model")
    return {"agent": os.path.basename(path)[6:-6], "kind": meta.get("taskKind") or ("workflow" if "/workflows/" in path else "subagent"),
            "type": meta.get("agentType"), "depth": meta.get("spawnDepth", 1) or 1, "parent": meta.get("parentAgentId"),
            "tool_use": meta.get("toolUseId"), "model": family(model), "start": f["first"], "end": f["last"],
            "cost": sum(c for _, c, _ in f["msgs"].values()), "peak_ctx": max((x for _, _, x in f["msgs"].values()), default=0),
            "commits": f["commits"]}


def concurrent(spans):
    """O-fanout: most workers whose [start, end] overlap at one instant."""
    ev = sorted([(s, 1) for s, e in spans] + [(e, -1) for s, e in spans], key=lambda x: (x[0], -x[1]))
    n = best = 0
    for _, k in ev:
        n += k
        best = max(best, n)
    return best


def session(sid, project, main, subs, prices):
    """O-session: one delegating session -> record, or None if it launched no worker."""
    orch = scan_file(main, prices) if main else scan_file(os.devnull, prices)
    files = {p: scan_file(p, prices) for p in subs}
    ws = []
    for p, f in files.items():
        try:
            with open(p[:-6] + ".meta.json") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            meta = {}
        if f["first"]:
            ws.append(worker_record(p, meta, f))
    if not ws:
        return None
    launchers = [("orchestrator", orch)] + [(os.path.basename(p)[6:-6], f) for p, f in files.items()]
    for who, f in launchers:  # O-link: the transcript holding the launch tool_use is the launcher
        for w in ws:
            if w["tool_use"] in f["launches"]:
                lt = f["launches"][w["tool_use"]]
                res = f["results"].get(w["tool_use"], (0, False, None))
                notes = f["notes"].get(w["tool_use"], [])
                w.update(launcher=who, launched=lt["ts"], turn=lt["turn"],
                         result_tokens=res[0] + sum(n for n, _ in notes),
                         error=res[1] or res[2] in ERROR_STATUS or any(s in ERROR_STATUS for _, s in notes))
    for w in ws:
        w.setdefault("launcher", None)
        w["start"] = w.get("launched") or w["start"]
        w["dur_s"] = round((w["end"] - w["start"]).total_seconds())
        w["huge"] = (w.get("result_tokens") or 0) > HUGE_RESULT_TOKENS
    top = sorted((w for w in ws if w["launcher"] == "orchestrator"), key=lambda w: w["start"])
    turns = collections.OrderedDict()
    for w in top:
        turns.setdefault(w["turn"], []).append(w)
    batches = list(turns.values())
    committed = 0
    for i, b in enumerate(batches):  # O-commit: a batch's workers committed, or the orchestrator did before the next batch
        nxt = batches[i + 1][0]["start"] if i + 1 < len(batches) else None
        committed += any(w["commits"] for w in b) or any(b[0]["start"] <= t and (nxt is None or t < nxt) for t in orch["commits"])
    spans = [(w["start"], w["end"]) for w in ws if w["depth"] == 1]
    overl = sum(any(o is not w and o["start"] < w["end"] and w["start"] < o["end"] for o in ws if o["depth"] == 1)
                for w in ws if w["depth"] == 1)
    oc = sum(c for _, c, _ in orch["msgs"].values())
    wc = sum(w["cost"] for w in ws)
    rt = [w["result_tokens"] for w in top if w.get("result_tokens") is not None]
    s = {"v": 1, "harness": HARNESS, "session_id": sid, "project": project, "start": iso(min([w["start"] for w in ws] + [orch["first"] or ws[0]["start"]])),
         "workers": len(ws), "workers_linked": sum(w["launcher"] is not None for w in ws),
         "batches": len(batches), "max_batch": max((len(b) for b in batches), default=0),
         "max_concurrent": concurrent(spans) if spans else 0, "max_depth": max(w["depth"] for w in ws),
         "parallel_share": round(overl / len(spans), 4) if spans else None,
         "models": dict(collections.Counter(w["model"] for w in ws).most_common()),
         "orchestrator_cost": round(oc, 4), "worker_cost": round(wc, 4),
         "worker_cost_share": round(wc / (oc + wc), 4) if oc + wc else None,
         "worker_peak_ctx_p50": pct([w["peak_ctx"] for w in ws], .5), "worker_peak_ctx_p90": pct([w["peak_ctx"] for w in ws], .9),
         "worker_dur_s_p50": pct([w["dur_s"] for w in ws], .5), "worker_dur_s_p90": pct([w["dur_s"] for w in ws], .9),
         "result_tokens": sum(rt), "result_tokens_p50": pct(rt, .5), "result_tokens_max": max(rt, default=None),
         "huge_results": sum(w["huge"] for w in top), "batches_committed": committed,
         "worker_errors": sum(bool(w.get("error")) for w in ws), "orchestrator_peak_ctx": max((x for _, _, x in orch["msgs"].values()), default=0)}
    s["topology"] = next(name for name, rule in TOPOLOGIES if rule(s))
    s["worker_list"] = [{k: (iso(v) if isinstance(v, datetime) else v) for k, v in w.items() if k not in ("commits", "turn")}
                        | {"commits": len(w["commits"])} for w in ws]
    return s


def scan(root, since):
    """O-sessions: <project>/<sid>.jsonl and <project>/<sid>/subagents/**/agent-*.jsonl, touched since `since`."""
    root = os.path.expanduser(root)
    sids = {}
    for p in glob.glob(os.path.join(root, "*", "*.jsonl")):
        sids.setdefault((os.path.basename(os.path.dirname(p)), os.path.basename(p)[:-6]), [None, []])[0] = p
    for p in glob.glob(os.path.join(root, "*", "*", "subagents", "**", "agent-*.jsonl"), recursive=True):
        rel = os.path.relpath(p, root).split(os.sep)
        sids.setdefault((rel[0], rel[1]), [None, []])[1].append(p)
    prices, out = load_prices(), []
    for (project, sid), (main, subs) in sorted(sids.items()):
        if not subs or max(os.path.getmtime(x) for x in subs + ([main] if main else [])) < since.timestamp():
            continue
        s = session(sid, project, main, subs, prices)
        if s:
            out.append(s)
    return out


def summarize(recs):
    """O-summary + O-readout: totals over delegating sessions, and the compact readout section with 1-3 findings."""
    ws = [w for r in recs for w in r["worker_list"]]
    top = [w for w in ws if w.get("launcher") == "orchestrator" and w.get("result_tokens") is not None]
    oc, wc = sum(r["orchestrator_cost"] for r in recs), sum(r["worker_cost"] for r in recs)
    mc = collections.Counter()
    for w in ws:
        mc[w["model"]] += w["cost"]
    batches, committed = sum(r["batches"] for r in recs), sum(r["batches_committed"] for r in recs)
    s = {"sessions": len(recs), "workers": len(ws), "topologies": dict(collections.Counter(r["topology"] for r in recs).most_common()),
         "orchestrator_cost": round(oc, 2), "worker_cost": round(wc, 2), "worker_cost_share": round(wc / (oc + wc), 3) if oc + wc else None,
         "worker_cost_by_model": {k: round(v, 2) for k, v in mc.most_common()},
         "max_concurrent": max((r["max_concurrent"] for r in recs), default=0),
         "worker_peak_ctx_p50": pct([w["peak_ctx"] for w in ws], .5), "worker_peak_ctx_p90": pct([w["peak_ctx"] for w in ws], .9),
         "worker_dur_s_p50": pct([w["dur_s"] for w in ws], .5),
         "result_tokens": sum(w["result_tokens"] for w in top), "result_tokens_p50": pct([w["result_tokens"] for w in top], .5),
         "result_tokens_p90": pct([w["result_tokens"] for w in top], .9), "huge_results": sum(w["huge"] for w in top),
         "huge_threshold": HUGE_RESULT_TOKENS, "batches": batches, "batches_committed": committed,
         "worker_errors": sum(bool(w.get("error")) for w in ws), "workers_unlinked": sum(w.get("launcher") is None for w in ws)}
    findings = []
    if recs:
        big = max(recs, key=lambda r: r["result_tokens"])
        findings.append(f"top session absorbed {big['result_tokens']} result tok from {big['workers']} workers")
    if wc:
        k, v = mc.most_common(1)[0]
        findings.append(f"{k} = {v / wc:.0%} of worker cost")
    if batches:
        findings.append(f"{committed}/{batches} batches then commit")
    ro = {k: s[k] for k in ("sessions", "workers", "topologies", "worker_cost_share", "max_concurrent", "worker_peak_ctx_p90",
                            "result_tokens_p90", "huge_results", "worker_errors")}
    while findings:
        ro["findings"] = findings
        if len(json.dumps(ro)) < READOUT_BYTES:
            break
        findings = findings[:-1]
        ro.pop("findings")
    s["readout"] = ro
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--root", help=f"transcripts dir (default: config readers.paths.claude-code, else {ROOT})")
    ap.add_argument("--config")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config(a.config)
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=a.days)
    recs = scan(a.root or cfg["readers"]["paths"].get(HARNESS) or ROOT, since)
    out = a.out or data_dir(cfg)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "orchestration.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    s = summarize(recs)
    with open(os.path.join(out, "orchestration_summary.json"), "w") as f:
        json.dump(s, f, indent=1)
    print(f"orchestration: {s['sessions']} delegating sessions, {s['workers']} workers, {s['topologies']}, "
          f"worker cost share {s['worker_cost_share']}, result tok p50/p90 {s['result_tokens_p50']}/{s['result_tokens_p90']}, "
          f"{s['huge_results']} > {HUGE_RESULT_TOKENS} -> {out}")


if __name__ == "__main__":
    main()
