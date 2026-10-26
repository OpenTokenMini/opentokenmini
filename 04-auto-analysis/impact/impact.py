#!/usr/bin/env python3
"""Link agent sessions to git commits (metadata only) and cost them. Specs: impact/METHOD.md (L-*).

python3 04-auto-analysis/impact/impact.py [--days N] [--harness ID] [--config PATH] [--out DIR] [--sessions FILE] [--decisions FILE]
Reads sessions.jsonl (+ decisions.jsonl for commit_link answers), writes impact.jsonl + impact_summary.json.
"""
import argparse, hashlib, importlib.util, json, os, re, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector
_spec = importlib.util.spec_from_file_location("impact_connectors", os.path.join(os.path.dirname(os.path.abspath(__file__)), "connectors.py"))
_conn = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_conn)
VCS = _conn.VCS  # name -> commits(repo, since, until, cfg); stage-unique module name avoids clashes in one test process

DAYS = 30
PRE_MIN = 5        # L-window: minutes before session start
POST_MIN = 30      # L-window: minutes after session end
MIN_CALLS = 10     # L-assign: sessions with fewer API calls lose to any bigger in-window session (tiny automated runs)
# L-assign: tools that can touch files or run `git commit`; a session that used one beats one that did not
WRITE_TOOLS = {"Bash", "bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "edit", "write", "exec", "apply_patch",
               "shell", "run_command", "write_to_file"}
OUTSIDE_P = 0.9    # L-outside: link_p of a trailer commit assigned to a session started outside any repo
MIN_P = 0.5        # L-decided: commit_link p below this = unlinked
LINK_OPTION = "yes"  # L-decided (= decide/points.json commit_link option): option of the commit_link decision whose probability is link_p
# L-trailer: trailer line regex -> harness id (first match wins); value stored in agent_trailer
AGENT_TRAILERS = [
    (r"^claude-session:|^co-authored-by:.*\bclaude\b", "claude-code"),
    (r"^co-authored-by:.*\bcodex\b", "codex"),
    (r"^co-authored-by:.*\bopencode\b", "opencode"),
    (r"^co-authored-by:.*\b(antigravity|gemini)\b", "antigravity"),
    (r"^co-authored-by:\s*pi\b", "pi"),
]
AGENT_RX = [(re.compile(rx, re.I), h) for rx, h in AGENT_TRAILERS]
ISO = "%Y-%m-%dT%H:%M:%SZ"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def h12(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def agent_of(commit):
    """L-trailer: harness id named by the first agent trailer, else None."""
    for t in commit["trailers"]:
        for rx, h in AGENT_RX:
            if rx.search(t.strip()):
                return h
    return None


def subject_of(session_id, shas):
    """L-subject: decision subject of a window candidate; changes when its commit set changes."""
    return f"{session_id}:{hashlib.sha256(','.join(sorted(shas)).encode()).hexdigest()[:8]}"


def distance(s, t):
    """L-assign: minutes from commit time t to the session's [start, end] (0 inside)."""
    a, b = ts(s["start"]), ts(s["end"])
    return 0.0 if a <= t <= b else min(abs((t - a).total_seconds()), abs((t - b).total_seconds())) / 60


def in_window(s, t):
    return ts(s["start"]) - timedelta(minutes=PRE_MIN) <= t <= ts(s["end"]) + timedelta(minutes=POST_MIN)


def rank(s, t):
    """L-assign sort key: big before tiny, writer before non-writer, then nearest, most calls, latest start."""
    writer = any(k in WRITE_TOOLS for k in s.get("tools") or {})
    return (s["calls"] < MIN_CALLS, not writer, distance(s, t), -s["calls"], -ts(s["start"]).timestamp(), s["session_id"])


def assign(commits, sessions):
    """L-assign: each commit to the best in-window session by rank(). -> {sid: [commit]}"""
    out = {}
    for c in commits:
        t = ts(c["ts"])
        cands = [s for s in sessions if in_window(s, t)]
        if cands:
            best = min(cands, key=lambda s: rank(s, t))
            out.setdefault(best["session_id"], []).append(c)
    return out


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def toplevel(path):
    return os.path.realpath(os.path.expanduser(path)).rstrip(os.sep)


def inside(repo, parent):
    """L-outside: repo is strictly below parent (nested repo committed to with `git -C` from the parent)."""
    return repo.startswith(parent + os.sep)


def decided(decisions):
    """L-decided: latest commit_link decision per subject -> p(LINK_OPTION)."""
    best = {}
    for d in decisions:
        if d.get("point") == "commit_link" and (d["subject"] not in best or d["ts"] >= best[d["subject"]][0]):
            best[d["subject"]] = (d["ts"], d["probabilities"].get(LINK_OPTION, 0.0))
    return {k: p for k, (_, p) in best.items()}


def record(s, label, link, p, commits, reverted_by):
    rows = [{"sha": c["sha"], "ts": c["ts"], "author": h12(c["email"]), "files": c["files"], "added": c["added"],
             "deleted": c["deleted"], "agent_trailer": agent_of(c), "on_default_branch": c["on_default_branch"],
             "reverted_by": reverted_by.get(c["sha"])} for c in sorted(commits, key=lambda c: c["ts"])]
    own = [c for c in commits if not c["reverts"]]  # L-revert: revert commits add no lines and are not kept
    return {"v": 1, "session_id": s["session_id"], "harness": s["harness"], "repo_label": label, "link": link,
            "link_p": p, "commits": rows, "added": sum(c["added"] for c in own), "deleted": sum(c["deleted"] for c in own),
            "commits_kept": sum(1 for c in own if c["sha"] not in reverted_by),
            "commits_reverted": sum(1 for c in own if c["sha"] in reverted_by)}


def link_repo(repo, sessions, vcs, cfg, answers, now, outside=()):
    """L-trailer, L-window, L-decided, L-revert for one repo; outside = L-outside sessions (trailer only)."""
    since = min(ts(s["start"]) for s in list(sessions) + list(outside)) - timedelta(minutes=PRE_MIN)
    commits = vcs(repo, since, now, cfg)
    reverted_by = {}
    for c in commits:  # L-revert: reverts are found up to now, not only in the window
        if c["reverts"]:
            for o in commits:
                if o["sha"].startswith(c["reverts"]):
                    reverted_by.setdefault(o["sha"], c["sha"])
    label = os.path.basename(repo)
    out, trailer_sids = [], set()
    by_harness = {}
    for c in commits:
        h = agent_of(c)
        if h:
            by_harness.setdefault(h, []).append(c)
    for h, cs in by_harness.items():
        own_ids = {s["session_id"] for s in sessions}
        for sid, mine in assign(cs, [s for s in list(sessions) + list(outside) if s["harness"] == h]).items():
            s = next(x for x in list(sessions) + list(outside) if x["session_id"] == sid)
            out.append(record(s, label, "trailer", 1.0 if sid in own_ids else OUTSIDE_P, mine, reverted_by))
            trailer_sids.add(sid)
    window = [c for c in commits if c["local"] and not agent_of(c)]
    for sid, mine in assign(window, [s for s in sessions if s["session_id"] not in trailer_sids]).items():
        s = next(x for x in sessions if x["session_id"] == sid)
        p = answers.get(subject_of(sid, [c["sha"] for c in mine]))
        if p is None or p >= MIN_P:
            out.append(record(s, label, "window", p, mine, reverted_by))
    return out


def shares(recs):
    """L-split: (session_id, repo_label) -> share of the session's linked commits in that record; sums to 1 per session."""
    n = {}
    for r in recs:
        if r["link_p"] is not None:
            n[r["session_id"]] = n.get(r["session_id"], 0) + len(r["commits"])
    return {(r["session_id"], r["repo_label"]): len(r["commits"]) / n[r["session_id"]] for r in recs if r["link_p"] is not None}


def summary_row(key, val, recs, cost, share):
    linked = [r for r in recs if r["link_p"] is not None]
    c = round(sum(cost[r["session_id"]] * share[(r["session_id"], r["repo_label"])] for r in linked), 6)
    kept = sum(r["commits_kept"] for r in linked)
    rev = sum(r["commits_reverted"] for r in linked)
    # L-cost: lines that survived = session added minus lines of its reverted commits
    lines = sum(max(0, r["added"] - sum(x["added"] for x in r["commits"] if x["reverted_by"])) for r in linked)
    return {key: val, "cost": c, "sessions": len({r["session_id"] for r in linked}), "commits_kept": kept,
            "commits_reverted": rev, "lines_added": lines,
            "cost_per_kept_commit": round(c / kept, 6) if kept else None,
            "cost_per_100_lines": round(c / lines * 100, 6) if lines else None,
            "revert_rate": round(rev / (kept + rev), 6) if kept + rev else None}


def run(sessions, cfg, answers, now, harness=None):
    vcs = connector(VCS, cfg["impact"]["vcs"], "impact.vcs")
    if harness:
        sessions = [s for s in sessions if s["harness"] == harness]
    repos = [toplevel(r) for r in cfg["impact"]["repos"]] or sorted({toplevel(s["repo"]) for s in sessions if s.get("repo")})
    recs = []
    for repo in repos:
        mine = [s for s in sessions if (s.get("repo") and toplevel(s["repo"]) == repo)
                or (not s.get("repo") and s.get("project") == os.path.basename(repo))]
        outside = [s for s in sessions if s not in mine and (not s.get("repo") or inside(repo, toplevel(s["repo"])))] \
            if cfg["impact"]["repos"] else []
        if (mine or outside) and os.path.isdir(repo):
            recs += link_repo(repo, mine, vcs, cfg, answers, now, outside)
    recs.sort(key=lambda r: (r["repo_label"], r["session_id"]))
    cost = {s["session_id"]: s["cost"]["total"] for s in sessions}
    linked = {r["session_id"] for r in recs if r["link_p"] is not None}
    share = shares(recs)
    summary = {"v": 1, "generated": now.strftime(ISO), "repos_scanned": len(repos), "sessions_total": len(sessions),
               "sessions_linked": len(linked),
               "by_repo": [summary_row("repo_label", k, [r for r in recs if r["repo_label"] == k], cost, share)
                           for k in sorted({r["repo_label"] for r in recs})],
               "by_harness": [summary_row("harness", k, [r for r in recs if r["harness"] == k], cost, share)
                              for k in sorted({r["harness"] for r in recs})],
               "unlinked_cost": round(sum(c for sid, c in cost.items() if sid not in linked), 6)}
    return recs, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--harness")
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--sessions")
    ap.add_argument("--decisions")
    a = ap.parse_args()
    cfg = load_config(a.config)
    d = data_dir(cfg)
    out = a.out or d
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff = now - timedelta(days=a.days)
    sessions = [s for s in read_jsonl(a.sessions or os.path.join(d, "sessions.jsonl")) if ts(s["end"]) >= cutoff]
    answers = decided(read_jsonl(a.decisions or os.path.join(d, "decisions.jsonl")))
    recs, summary = run(sessions, cfg, answers, now, a.harness)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "impact.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    with open(os.path.join(out, "impact_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    pending = sum(1 for r in recs if r["link_p"] is None)
    print(f"impact: {summary['sessions_linked']}/{summary['sessions_total']} sessions linked, "
          f"{pending} window candidates pending commit_link, {summary['repos_scanned']} repos -> {out}")


if __name__ == "__main__":
    main()
