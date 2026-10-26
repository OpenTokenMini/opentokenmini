#!/usr/bin/env python3
"""Link GitHub issues and PRs to commits and, through impact.jsonl, to sessions (metadata only). Specs: issues/METHOD.md (I-*).

python3 04-auto-analysis/issues/issues.py --repo PATH [--repo PATH ...] [--days N] [--out DIR] [--impact FILE] [--sessions FILE]
Reads GitHub via `gh api graphql` (read-only) + impact.jsonl + sessions.jsonl, writes issues.jsonl + issues_summary.json.
"""
import argparse, hashlib, json, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.config import load_config, data_dir

DAYS = 30
PAGE = 50            # I-fetch: nodes per GraphQL page
MAX_PAGES = 20       # I-fetch: per repo and kind; PAGE * MAX_PAGES caps what one run reads
PR_COMMITS = 100     # I-fetch: commits read per PR (GitHub max per page); longer PRs are truncated
# I-type: label (lowercase) -> ticket type; first matching label wins, PRs fall back to their closed issues
TYPE_LABELS = {"bug": "bug", "fix": "bug", "regression": "bug", "feature": "feature", "enhancement": "feature",
               "chore": "chore", "dependencies": "chore", "documentation": "docs", "docs": "docs"}
KEY_RX = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")             # I-keys: Jira/Linear keys in PR title or branch
REF_RX = re.compile(r"(?:^|[\s(])#(\d+)\b")                 # I-keys: "#12" in PR title
BRANCH_RX = re.compile(r"(?:^|/)(?:issue-|gh-)?(\d+)[-_/]")  # I-keys: "fix/12-name", "12-name", "gh-12_x"
REMOTE_RX = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
ISO = "%Y-%m-%dT%H:%M:%SZ"

FIELDS = {
    "pullRequests": "number state createdAt updatedAt closedAt mergedAt title headRefName author{login} "
                    "labels(first:20){nodes{name}} mergeCommit{oid} commits(first:%d){nodes{commit{oid}}} "
                    "closingIssuesReferences(first:20){nodes{number}}" % PR_COMMITS,
    "issues": "number state stateReason createdAt updatedAt closedAt author{login} labels(first:20){nodes{name}}",
}
QUERY = ("query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){%s(first:%d,after:$after,"
         "orderBy:{field:UPDATED_AT,direction:DESC}){pageInfo{hasNextPage endCursor} nodes{%s}}}}")


def h12(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12] if s else None


def gh_cli(args):
    """Run gh read-only; raises with gh's message on failure."""
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {p.stderr.strip()}")
    return p.stdout


def slug_of(repo):
    """I-repo: owner/name from the origin remote of a local clone, or None if not on GitHub."""
    url = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = REMOTE_RX.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def fetch(slug, kind, cutoff, gh):
    """I-fetch: (nodes of kind updated at or after cutoff, truncated) newest first, paging until older or MAX_PAGES."""
    owner, name = slug.split("/")
    out, after = [], None
    for _ in range(MAX_PAGES):
        args = ["api", "graphql", "-f", f"query={QUERY % (kind, PAGE, FIELDS[kind])}", "-F", f"owner={owner}", "-F", f"name={name}"]
        conn = json.loads(gh(args + (["-f", f"after={after}"] if after else [])))["data"]["repository"][kind]
        fresh = [n for n in conn["nodes"] if n["updatedAt"] >= cutoff]
        out += fresh
        if len(fresh) < len(conn["nodes"]) or not conn["pageInfo"]["hasNextPage"]:
            return out, False
        after = conn["pageInfo"]["endCursor"]
    return out, True


def labels(n):
    return sorted(l["name"] for l in n["labels"]["nodes"])


def type_of(lbls):
    """I-type: first label in TYPE_LABELS, else None."""
    return next((TYPE_LABELS[l.lower()] for l in lbls if l.lower() in TYPE_LABELS), None)


def keys_of(title, branch):
    """I-keys: (ticket keys, issue numbers) parsed from PR title and branch; title and branch are not stored."""
    keys = sorted(set(KEY_RX.findall(title or "")) | set(KEY_RX.findall(branch or "")))
    nums = {int(n) for n in REF_RX.findall(title or "")} | {int(n) for n in BRANCH_RX.findall(branch or "")}
    return keys, nums


def read_jsonl(path):
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def sha_index(impact_recs):
    """I-join: (repo_label, sha) -> session_id from linked impact records; session_id -> its linked commit count."""
    by_sha, n = {}, {}
    for r in impact_recs:
        if r["link_p"] is None:
            continue
        for c in r["commits"]:
            by_sha[(r["repo_label"], c["sha"])] = r["session_id"]
            n[r["session_id"]] = n.get(r["session_id"], 0) + 1
    return by_sha, n


def repo_records(label, prs, issues, by_sha, n, cost):
    """I-pr, I-issue, I-join, I-cost for one repo."""
    known = {i["number"] for i in issues}
    out, closed_by = [], {}
    for p in prs:
        shas = [c["commit"]["oid"] for c in p["commits"]["nodes"]]
        merge = (p.get("mergeCommit") or {}).get("oid")
        hits = {}  # I-join: session -> matched commits of this PR (merge sha counted when the squash landed locally)
        for s in set(shas + ([merge] if merge else [])):
            sid = by_sha.get((label, s))
            if sid:
                hits[sid] = hits.get(sid, 0) + 1
        keys, nums = keys_of(p["title"], p["headRefName"])
        closing = sorted({i["number"] for i in p["closingIssuesReferences"]["nodes"]} | (nums & known))
        for i in closing:
            closed_by.setdefault(i, []).append(p["number"])
        lb = labels(p)
        out.append({"v": 1, "kind": "pr", "source": "github", "repo_label": label, "number": p["number"],
                    "state": "merged" if p["mergedAt"] else p["state"].lower(), "state_reason": None, "type": type_of(lb),
                    "created": p["createdAt"], "closed": p["closedAt"], "merged": p["mergedAt"],
                    "author": h12((p.get("author") or {}).get("login")), "labels": lb, "keys": keys, "issues": closing,
                    "prs": [], "commits": shas, "merge_sha": merge, "session_ids": sorted(hits),
                    "cost": round(sum(cost.get(s, 0.0) * k / n[s] for s, k in hits.items()), 6)})
    by_num = {r["number"]: r for r in out}
    for i in issues:
        lb, mine = labels(i), sorted(set(closed_by.get(i["number"], [])))
        prs_ = [by_num[k] for k in mine]
        out.append({"v": 1, "kind": "issue", "source": "github", "repo_label": label, "number": i["number"],
                    "state": i["state"].lower(), "state_reason": (i.get("stateReason") or "").lower() or None,
                    "type": type_of(lb), "created": i["createdAt"], "closed": i["closedAt"], "merged": None,
                    "author": h12((i.get("author") or {}).get("login")), "labels": lb, "keys": [], "issues": [],
                    "prs": mine, "commits": [], "merge_sha": None,
                    "session_ids": sorted({s for r in prs_ for s in r["session_ids"]}),
                    # I-cost: a PR closing k issues gives each 1/k of its cost
                    "cost": round(sum(r["cost"] / len(r["issues"]) for r in prs_), 6)})
    for r in out:  # I-type: untyped PR takes the type of its first typed closed issue
        if r["kind"] == "pr" and r["type"] is None:
            r["type"] = next((x["type"] for x in out if x["kind"] == "issue" and x["number"] in r["issues"] and x["type"]), None)
    return out


def summarize(recs, repos, truncated, now):
    """I-summary: counts, ticketless share, spend per type (PR cost only, so nothing is counted twice)."""
    prs = [r for r in recs if r["kind"] == "pr"]
    iss = [r for r in recs if r["kind"] == "issue"]
    types = sorted({r["type"] or "none" for r in recs})
    return {"v": 1, "generated": now.strftime(ISO), "repos_scanned": repos, "truncated": truncated, "prs": len(prs),
            "prs_merged": sum(r["state"] == "merged" for r in prs),
            "prs_with_session": sum(bool(r["session_ids"]) for r in prs),
            "prs_without_ticket": sum(not r["issues"] and not r["keys"] for r in prs),
            "issues": len(iss), "issues_closed_without_pr": sum(r["state"] == "closed" and not r["prs"] for r in iss),
            "cost_linked": round(sum(r["cost"] for r in prs), 6),
            "by_type": [{"type": t, "prs": sum((r["type"] or "none") == t for r in prs),
                         "issues": sum((r["type"] or "none") == t for r in iss),
                         "sessions": len({s for r in prs if (r["type"] or "none") == t for s in r["session_ids"]}),
                         "cost": round(sum(r["cost"] for r in prs if (r["type"] or "none") == t), 6)} for t in types]}


def run(repos, impact_recs, sessions, now, days=DAYS, gh=gh_cli):
    cutoff = (now - timedelta(days=days)).strftime(ISO)
    by_sha, n = sha_index(impact_recs)
    cost = {s["session_id"]: s["cost"]["total"] for s in sessions}
    recs, scanned, truncated = [], 0, []
    for repo in repos:
        repo = os.path.realpath(os.path.expanduser(repo)).rstrip(os.sep)
        slug = slug_of(repo)
        if not slug:
            print(f"issues: {repo}: no GitHub origin remote, skipped", file=sys.stderr)
            continue
        try:
            (prs, tp), (issues, ti) = fetch(slug, "pullRequests", cutoff, gh), fetch(slug, "issues", cutoff, gh)
        except RuntimeError as e:  # I-repo: deleted, renamed or no access; one bad repo does not stop the rest
            print(f"issues: {repo}: {e}, skipped", file=sys.stderr)
            continue
        scanned += 1
        label = os.path.basename(repo)
        truncated += [f"{label}:{k}" for k, t in (("pullRequests", tp), ("issues", ti)) if t]
        recs += repo_records(label, prs, issues, by_sha, n, cost)
    recs.sort(key=lambda r: (r["repo_label"], r["kind"], r["number"]))
    return recs, summarize(recs, scanned, truncated, now)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", action="append", required=True, help="local clone with a GitHub origin; repeatable")
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--impact")
    ap.add_argument("--sessions")
    a = ap.parse_args()
    d = data_dir(load_config(a.config))
    out = a.out or d
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recs, summary = run(a.repo, read_jsonl(a.impact or os.path.join(d, "impact.jsonl")),
                        read_jsonl(a.sessions or os.path.join(d, "sessions.jsonl")), now, a.days)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "issues.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)
    with open(os.path.join(out, "issues_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(f"issues: {summary['prs']} PRs ({summary['prs_with_session']} with a session, {summary['prs_without_ticket']} "
          f"without ticket), {summary['issues']} issues, {summary['repos_scanned']} repos -> {out}")


if __name__ == "__main__":
    main()
