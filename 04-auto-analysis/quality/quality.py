#!/usr/bin/env python3
"""Quality signals per session and per commit from Claude Code transcripts + local git. Specs: quality/METHOD.md (Q-*).

python3 04-auto-analysis/quality/quality.py [--days N] [--repo PATH ...] [--config PATH] [--out DIR] [--impact FILE] [--transcripts DIR]
Reads transcripts (tool calls and results, in memory only), impact.jsonl, git log --name-only; writes quality.jsonl + quality_summary.json.
"""
import argparse, glob, json, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir

DAYS = 7
ROOT = "~/.claude/projects"                       # Claude Code transcripts; readers.paths.claude-code overrides
REWORK_HOURS = 24                                 # Q-rework-*: a later edit/commit on the same file within this counts
SHELL_TOOLS = ("Bash",)                           # Q-test, Q-risk: tools whose input.command is a shell command
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")  # Q-rework-session: tools whose input names a file
TEST_RX = re.compile(r"(?:^|[\s;&|(])(?:python3? -m (?:unittest|pytest)|pytest|npm (?:run )?test|yarn test|pnpm test"
                     r"|go test|cargo test|make test|mvn test|gradle test|jest|vitest|rspec|bun test)\b")
FAIL_RX = re.compile(r"^FAILED \(|\b\d+ failed\b|^FAIL[: ]|^--- FAIL|test result: FAILED|Tests:.*\bfailed\b", re.M)
RISK_RX = {  # Q-risk: first match per class; the command text is never written out
    "destructive": re.compile(r"\brm -[a-z]*r[a-z]*f|\brm -[a-z]*f[a-z]*r|git reset --hard|git push\b.*(?:--force|\s-f\b)"
                              r"|git clean -[a-z]*f|git branch -D|git checkout -- \.|\bmkfs|\bdd if=|drop (?:table|database)", re.I),
    "exfiltration": re.compile(r"\bcurl\b.*(?:\s-d\b|--data|\s-F\b|\s-T\b|--upload-file)|\bscp\b|\bnc\s|wget\b.*--post"
                               r"|\brsync\b.*\s\S+:"),
    "secrets": re.compile(r"(?:^|[\s/'\"])\.env\b|id_rsa|id_ed25519|\.ssh/|\.aws/credentials|\.netrc|\bprintenv\b"
                          r"|\b(?:API_KEY|SECRET|TOKEN|PASSWORD)\b"),
}
LOCAL_RX = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]")  # Q-risk: exfiltration to these hosts does not count
ISO = "%Y-%m-%dT%H:%M:%SZ"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(d):
    return d.strftime(ISO) if d else None


def rate(n, d):
    return round(n / d, 6) if d else None


def blank(sid):
    return {"sid": sid, "cwd": None, "start": None, "end": None, "calls": {}, "edits": [], "tests": []}


def scan(root, since):
    """Q-read: session_id -> tool calls with result, edits (file, ts), test runs (ts, passed)."""
    out = {}
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if os.path.getmtime(path) < since.timestamp():
            continue
        with open(path, errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    t = ts(d["timestamp"])
                except (ValueError, KeyError, AttributeError):
                    continue
                c = (d.get("message") or {}).get("content")
                if t < since or not d.get("sessionId") or not isinstance(c, list):
                    continue
                s = out.setdefault(d["sessionId"], blank(d["sessionId"]))
                s["cwd"] = s["cwd"] or d.get("cwd")
                s["start"], s["end"] = min(s["start"] or t, t), max(s["end"] or t, t)
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        inp = b.get("input") or {}
                        s["calls"][b.get("id")] = {"name": b.get("name"), "ts": t, "error": None,
                                                   "cmd": inp.get("command") if b.get("name") in SHELL_TOOLS else None}
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if b.get("name") in EDIT_TOOLS and fp:
                            s["edits"].append((os.path.realpath(fp), t))
                    elif b.get("type") == "tool_result" and b.get("tool_use_id") and b["tool_use_id"] in s["calls"]:
                        call, body = s["calls"][b["tool_use_id"]], b.get("content")
                        text = body if isinstance(body, str) else " ".join(
                            x.get("text", "") for x in body or [] if isinstance(x, dict))
                        call["error"] = bool(b.get("is_error"))
                        if call["cmd"] and TEST_RX.search(call["cmd"]):  # Q-test
                            s["tests"].append((call["ts"], not (call["error"] or FAIL_RX.search(text))))
    return out


def reworked_files(sessions):
    """Q-rework-session: session_id -> files it edited that a later, different session edited within REWORK_HOURS."""
    by_file, out, win = {}, {}, timedelta(hours=REWORK_HOURS)
    for s in sessions.values():
        for fp, t in s["edits"]:
            by_file.setdefault(fp, []).append((t, s["sid"]))
    for fp, edits in by_file.items():
        edits.sort()
        for i, (t, sid) in enumerate(edits):
            if any(sid2 != sid and t < t2 <= t + win for t2, sid2 in edits[i + 1:]):
                out.setdefault(sid, set()).add(fp)
    return out


def git_log(repo, since):
    """Q-rework-commit: commits since `since` on any ref: [{sha, ts, files}] oldest first (author date)."""
    p = subprocess.run(["git", "-C", repo, "log", "--all", "--no-merges", "--name-only", "--format=%x00%H %aI",
                        f"--since={iso(since)}"], capture_output=True, text=True)
    out = []
    for chunk in p.stdout.split("\0")[1:]:
        head, *files = chunk.strip().split("\n")
        sha, t = head.split(" ")
        out.append({"sha": sha, "ts": ts(t), "files": {f for f in files if f}})
    return sorted(out, key=lambda c: c["ts"])


def risky(cmd, k):
    """Q-risk: cmd matches class k; exfiltration only when the matching line names no local host."""
    m = cmd and RISK_RX[k].search(cmd)
    if not m or k != "exfiltration":
        return bool(m)
    line = cmd[cmd.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0]
    return not LOCAL_RX.search(line)


def last_test(s, before):
    """Q-test-last: result of the session's last test run at or before `before`, or None."""
    runs = [ok for t, ok in sorted(s["tests"]) if before is None or t <= before] if s else []
    return None if not runs else ("pass" if runs[-1] else "fail")


def build(sessions, impact, logs):
    """Q-session, Q-commit records and the Q-summary. logs: repo_label -> git_log output."""
    rework, recs, win = reworked_files(sessions), [], timedelta(hours=REWORK_HOURS)
    linked = {}
    for r in impact:
        if r.get("link_p") is not None:
            linked.setdefault(r["session_id"], []).append(r)
    for sid, s in sorted(sessions.items()):
        calls = list(s["calls"].values())
        risk = {k: sum(1 for c in calls if risky(c["cmd"], k)) for k in RISK_RX}
        errs, fails = sum(1 for c in calls if c["error"]), sum(1 for _, ok in s["tests"] if not ok)
        files = {fp for fp, _ in s["edits"]}
        recs.append({"v": 1, "kind": "session", "harness": "claude-code", "session_id": sid,
                     "repo_label": os.path.basename(s["cwd"] or "") or None, "start": iso(s["start"]), "end": iso(s["end"]),
                     "tool_calls": len(calls), "tool_errors": errs, "tool_error_rate": rate(errs, len(calls)),
                     "test_runs": len(s["tests"]), "test_failed": fails, "last_test": last_test(s, None),
                     "risky": risk, "files_edited": len(files), "files_reworked": len(rework.get(sid, ())),
                     "commits": sorted(c["sha"] for r in linked.get(sid, []) for c in r["commits"])})
    for sid, rs in sorted(linked.items()):
        for r in rs:
            log = logs.get(r["repo_label"], [])
            for c in r["commits"]:
                me = next((g for g in log if g["sha"] == c["sha"]), None)
                later = [g["sha"] for g in log if me and g["sha"] != c["sha"] and me["ts"] < g["ts"] <= me["ts"] + win
                         and g["files"] & me["files"]]
                recs.append({"v": 1, "kind": "commit", "harness": r["harness"], "session_id": sid,
                             "repo_label": r["repo_label"], "sha": c["sha"], "ts": c["ts"],
                             "last_test": last_test(sessions.get(sid), ts(c["ts"])),
                             "reworked_by": later if me else None, "reverted_by": c.get("reverted_by")})
    return recs, summarize(recs)


def summarize(recs):
    ss, cs = [r for r in recs if r["kind"] == "session"], [r for r in recs if r["kind"] == "commit"]
    tot = lambda k, xs: sum(r[k] for r in xs)
    known = [c for c in cs if c["reworked_by"] is not None]
    return {"v": 1, "sessions": len(ss), "tool_calls": tot("tool_calls", ss), "tool_error_rate": rate(tot("tool_errors", ss), tot("tool_calls", ss)),
            "sessions_with_tests": sum(1 for r in ss if r["test_runs"]), "test_runs": tot("test_runs", ss),
            "test_fail_rate": rate(tot("test_failed", ss), tot("test_runs", ss)),
            "file_rework_rate": rate(tot("files_reworked", ss), tot("files_edited", ss)),
            "risky": {k: sum(r["risky"][k] for r in ss) for k in RISK_RX}, "commits": len(cs),
            "commit_rework_rate": rate(sum(1 for c in known if c["reworked_by"]), len(known)),
            "commits_last_test_fail": sum(1 for c in cs if c["last_test"] == "fail"),
            "commits_without_test": sum(1 for c in cs if c["last_test"] is None)}


def toplevel(path):
    p = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for a in ("--config", "--out", "--impact", "--transcripts"):
        ap.add_argument(a)
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--repo", action="append", default=[], help="git repo to scan for Q-rework-commit; repeatable")
    a = ap.parse_args()
    cfg = load_config(a.config)
    d = data_dir(cfg)
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    root = a.transcripts or os.path.expanduser((cfg.get("readers", {}).get("paths") or {}).get("claude-code") or ROOT)
    sessions = scan(root, since)
    impact = []
    if os.path.exists(a.impact or os.path.join(d, "impact.jsonl")):
        with open(a.impact or os.path.join(d, "impact.jsonl")) as f:
            impact = [r for r in map(json.loads, filter(str.strip, f)) if r["session_id"] in sessions]
    repos = a.repo + cfg.get("impact", {}).get("repos", []) + [s["cwd"] for s in sessions.values() if s["cwd"]] \
        + list({os.path.dirname(fp) for s in sessions.values() for fp, _ in s["edits"]})
    tops = {t for t in (toplevel(os.path.expanduser(r)) for r in set(repos) if os.path.isdir(os.path.expanduser(r))) if t}
    labels = {r["repo_label"] for r in impact}
    logs = {os.path.basename(t): git_log(t, since - timedelta(hours=REWORK_HOURS)) for t in tops if os.path.basename(t) in labels}
    recs, summary = build(sessions, impact, logs)
    out = a.out or d
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "quality.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    with open(os.path.join(out, "quality_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
