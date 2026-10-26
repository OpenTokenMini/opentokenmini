#!/usr/bin/env python3
"""Read CI runs (GitHub Actions via gh CLI, metadata only) and join them to impact.jsonl commits. Specs: deployments/METHOD.md (D-*).

python3 04-auto-analysis/deployments/deployments.py [--repo PATH|OWNER/NAME ...] [--days N] [--ci NAME] [--config PATH] [--impact FILE] [--out DIR]
Reads CI runs per repo + impact.jsonl, writes deployments.jsonl.
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir, connector

DAYS = 30
MAX_RUNS = 500           # D-scan: gh run list --limit per repo
MAX_FAILED_DETAIL = 20   # D-failed-step: failed runs per repo whose jobs are fetched (one gh call each)
CI_DEFAULT = "github_actions"
RUN_FIELDS = "databaseId,workflowName,event,headSha,headBranch,status,conclusion,createdAt,startedAt,updatedAt"
FAILED = {"failure", "timed_out", "startup_failure"}  # D-rate: conclusions counted as failed
PASSED = {"success"}                                  # D-rate: cancelled/skipped/neutral count as neither
ISO = "%Y-%m-%dT%H:%M:%SZ"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def gh(args, cwd=None):
    """Run gh, return parsed JSON; raises on a non-zero exit (not authenticated, no remote, ...)."""
    p = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {p.stderr.strip()}")
    return json.loads(p.stdout or "null")


def target(repo):
    """D-repo: local path -> (cwd, [], basename); OWNER/NAME -> (None, ['-R', repo], NAME)."""
    path = os.path.realpath(os.path.expanduser(repo))
    if os.path.isdir(path):
        return path, [], os.path.basename(path.rstrip(os.sep))
    return None, ["-R", repo], repo.rstrip("/").rsplit("/", 1)[-1]


def failed_step(run_id, cwd, sel, run=gh):
    """D-failed-step: '<job> / <step>' of the first failed step of the first failed job, else None."""
    jobs = (run(["run", "view", str(run_id), "--json", "jobs", *sel], cwd) or {}).get("jobs") or []
    for j in jobs:
        if j.get("conclusion") in FAILED:
            for s in j.get("steps") or []:
                if s.get("conclusion") in FAILED:
                    return f"{j['name']} / {s['name']}"
            return j["name"]
    return None


def github_actions(repo, since, run=gh):
    """D-scan: workflow runs created at or after since (datetime, UTC) -> list of run dicts (see METHOD.md)."""
    cwd, sel, label = target(repo)
    raw = run(["run", "list", "--limit", str(MAX_RUNS), "--json", RUN_FIELDS,
               "--created", f">={since.strftime('%Y-%m-%d')}", *sel], cwd) or []
    out, detailed = [], 0
    for r in sorted(raw, key=lambda r: r["createdAt"]):
        if ts(r["createdAt"]) < since:
            continue
        done = r["status"] == "completed" and r.get("startedAt") and r.get("updatedAt")
        step = None
        if r.get("conclusion") in FAILED and detailed < MAX_FAILED_DETAIL:
            step, detailed = failed_step(r["databaseId"], cwd, sel, run), detailed + 1
        out.append({"run_id": str(r["databaseId"]), "repo_label": label, "workflow": r["workflowName"],
                    "event": r["event"], "head_sha": r["headSha"].lower(), "head_branch": r.get("headBranch") or None,
                    "status": r["status"], "conclusion": r.get("conclusion") or None,
                    "created": ts(r["createdAt"]).strftime(ISO),
                    "duration_s": max(0, int((ts(r["updatedAt"]) - ts(r["startedAt"])).total_seconds())) if done else None,
                    "failed_step": step})
    return out


def gitlab_ci(repo, since, run=gh):
    raise NotImplementedError("gitlab_ci: placeholder; list pipelines via glab or the REST API and return the same dicts")


CI = {"github_actions": github_actions, "gitlab_ci": gitlab_ci}


def commit_index(impact_recs):
    """D-join: (repo_label, sha) -> impact record that holds the commit; only linked records (link_p non-null)."""
    idx = {}
    for r in impact_recs:
        if r["link_p"] is not None:
            for c in r["commits"]:
                idx[(r["repo_label"], c["sha"].lower())] = r
    return idx


def join(runs, idx, ci):
    """D-join: one deployments record per run; session fields from the impact record whose commit is the run's head."""
    out = []
    for r in runs:
        m = idx.get((r["repo_label"], r["head_sha"]))
        if m is None:  # impact may hold full shas and CI short ones, or the reverse: match on prefix
            m = next((v for (lab, sha), v in idx.items() if lab == r["repo_label"]
                      and (sha.startswith(r["head_sha"]) or r["head_sha"].startswith(sha))), None)
        out.append({"v": 1, "ci": ci, **r, "session_id": m["session_id"] if m else None,
                    "harness": m["harness"] if m else None, "link": m["link"] if m else None,
                    "link_p": m["link_p"] if m else None})
    return out


def rates(recs):
    """D-rate: failure rate of completed pass/fail runs, agent-linked vs the rest (repo baseline)."""
    def rate(rs):
        n = [r for r in rs if r["conclusion"] in FAILED | PASSED]
        return (round(sum(r["conclusion"] in FAILED for r in n) / len(n), 6) if n else None), len(n)
    return {"agent": rate([r for r in recs if r["session_id"]]), "baseline": rate([r for r in recs if not r["session_id"]])}


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def run(repos, impact_recs, since, ci=CI_DEFAULT, gh_run=gh):
    fetch = connector(CI, ci, "--ci")
    recs, errors = [], []
    for repo in repos:
        try:
            recs += fetch(repo, since, gh_run)
        except (RuntimeError, NotImplementedError) as e:  # one bad repo (no remote, no access) does not stop the rest
            errors.append(f"{repo}: {e}")
    recs = join(recs, commit_index(impact_recs), ci)
    recs.sort(key=lambda r: (r["repo_label"], r["created"], r["run_id"]))
    return recs, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", action="append", help="local repo path or OWNER/NAME; repeatable")
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--ci", default=CI_DEFAULT)
    ap.add_argument("--config")
    ap.add_argument("--impact")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config(a.config)
    d = data_dir(cfg)
    repos = a.repo or cfg["impact"]["repos"] or [os.getcwd()]  # D-repo
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=a.days)
    recs, errors = run(repos, read_jsonl(a.impact or os.path.join(d, "impact.jsonl")), since, a.ci)
    out = a.out or d
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "deployments.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    for e in errors:
        print(f"deployments: skipped {e}", file=sys.stderr)
    rt = rates(recs)
    print(f"deployments: {len(recs)} runs, {sum(1 for r in recs if r['session_id'])} linked to sessions, "
          f"failure rate agent {rt['agent'][0]} (n={rt['agent'][1]}) vs baseline {rt['baseline'][0]} "
          f"(n={rt['baseline'][1]}), {len(repos)} repos -> {out}")


if __name__ == "__main__":
    main()
