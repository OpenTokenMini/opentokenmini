"""Run the batch stages in flow order, each as a subprocess; stop at the first nonzero exit.

Usage: python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run] [--no-network]
Stages: normalize readers analyze impact decide impact2 quality mcp orchestration context orch_ux deployments issues (impact2 = impact again, applies commit_link answers).
Data dir and config come from the env each stage already reads ($OTM_DATA_DIR, $OTM_CONFIG, 01-deploy/config.json).
normalize turns raw OTel (otel/) into events/otel.jsonl; analyze dedups it against transcripts (M-dedup).
deployments and issues are optional network stages (gh CLI, read-only): skipped, with a log line, when NETWORK is False,
--no-network is given, gh is missing or not authenticated, or there are no repos. quality, mcp, orchestration, context and orch_ux are local readers (no network).
These seven are optional: their compact summaries go to readout.json, and a failure there is written as {"skipped": reason}
and the pipeline goes on; a failure in any other stage stops it.
The collector (long-running) is not part of this; run it as in README.md.
"""
import argparse, collections, importlib.util, json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo: <repo>/03-analyze/pipeline.py
DAYS = 30
NETWORK = True      # False: never run the network stages (same as --no-network on every run)
MAX_REPOS = 20      # network stages: repos queried when derived from sessions (most linked sessions first)
READOUT = "readout.json"  # in the data dir; sections "quality", "mcp", "orchestration", "context", "orch_ux", "deployments", "issues" (output.md)
MCP_TOP = 5         # readout.mcp: servers_used keeps the servers with the most context tokens
REASON_CHARS = 200  # readout: a failed stage's reason is cut to this many characters
ISO = "%Y-%m-%dT%H:%M:%SZ"
# name, script, takes --days, main output (relative to the data dir), optional: None (failure stops the pipeline),
# "local" (failure -> readout {"skipped": reason}) or "network" (same, plus gets --repo and may be skipped before running)
STAGES = [
    ("normalize", "02-measure/collector/normalize.py", True, "events/otel.jsonl", None),
    ("readers", "02-measure/readers/readers.py", True, "events/transcript.jsonl", None),
    ("analyze", "03-analyze/analyze/analyze.py", True, "analysis.json", None),
    ("impact", "04-auto-analysis/impact/impact.py", True, "impact_summary.json", None),
    ("decide", "06-optional/decide/decide.py", False, "decisions.jsonl", None),
    ("impact2", "04-auto-analysis/impact/impact.py", True, "impact_summary.json", None),
    ("quality", "04-auto-analysis/quality/quality.py", True, "quality_summary.json", "local"),
    ("mcp", "04-auto-analysis/mcp-usage/mcp_usage.py", True, "mcp_usage.jsonl", "local"),
    ("orchestration", "04-auto-analysis/orchestration/orchestration.py", True, "orchestration.jsonl", "local"),
    ("context", "04-auto-analysis/context/context.py", True, "context.json", "local"),
    ("orch_ux", "04-auto-analysis/orch-ux/orch_ux.py", True, "orch_ux.json", "local"),
    ("deployments", "04-auto-analysis/deployments/deployments.py", True, "deployments.jsonl", "network"),
    ("issues", "04-auto-analysis/issues/issues.py", True, "issues_summary.json", "network"),
]
NAMES = [s[0] for s in STAGES]


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def toplevel(path):
    p = subprocess.run(["git", "-C", os.path.expanduser(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def repos_for(cfg, data):
    """Repos for the network stages: config impact.repos, else the git toplevels of sessions impact linked."""
    if cfg["impact"]["repos"]:
        return [toplevel(r) or r for r in cfg["impact"]["repos"]]
    linked = {r["session_id"] for r in read_jsonl(os.path.join(data, "impact.jsonl")) if r.get("link_p") is not None}
    n = collections.Counter()
    for s in read_jsonl(os.path.join(data, "sessions.jsonl")):
        repo = os.path.expanduser(s.get("repo") or "")  # sessions may store "~/..."
        if s["session_id"] in linked and repo and os.path.isdir(repo):
            n[repo] += 1
    tops = collections.Counter()
    for path, k in n.items():
        top = toplevel(path)
        if top:
            tops[top] += k
    return [r for r, _ in sorted(tops.items(), key=lambda x: (-x[1], x[0]))[:MAX_REPOS]]


def gh_problem():
    """None if gh is installed and authenticated, else why not."""
    if not shutil.which("gh"):
        return "gh not found"
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        return "gh not authenticated"
    return None


def load(name, script):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def readout_deployments(data, repos):
    """Compact deployments section: agent-linked vs baseline failure rate (D-rate, computed by deployments.rates)."""
    recs = read_jsonl(os.path.join(data, "deployments.jsonl"))
    rt = load("deployments", "04-auto-analysis/deployments/deployments.py").rates(recs)
    return {"repos": repos, "runs": len(recs), "runs_linked": sum(1 for r in recs if r["session_id"]),
            "agent": {"failure_rate": rt["agent"][0], "n": rt["agent"][1]},
            "baseline": {"failure_rate": rt["baseline"][0], "n": rt["baseline"][1]}}


def readout_issues(data):
    """Compact issues section from issues_summary.json (I-summary)."""
    with open(os.path.join(data, "issues_summary.json")) as f:
        s = json.load(f)
    return {"repos": s["repos_scanned"], "prs": s["prs"], "prs_merged": s["prs_merged"], "prs_linked": s["prs_with_session"],
            "ticketless_share": round(s["prs_without_ticket"] / s["prs"], 4) if s["prs"] else None,
            "cost_linked": s["cost_linked"], "issues": s["issues"],
            "issues_closed_without_pr": s["issues_closed_without_pr"], "truncated": s["truncated"]}


def readout_quality(data):
    """Compact quality section from quality_summary.json (Q-summary), field names as the reader writes them."""
    with open(os.path.join(data, "quality_summary.json")) as f:
        s = json.load(f)
    return {k: s[k] for k in ("sessions", "tool_error_rate", "test_runs", "test_fail_rate", "commits",
                              "commits_without_test", "risky", "file_rework_rate", "commit_rework_rate")}


def readout_mcp(data):
    """Compact mcp section from the server records of mcp_usage.jsonl (M-agg, M-unused)."""
    srv = [r for r in read_jsonl(os.path.join(data, "mcp_usage.jsonl")) if r["kind"] == "server"]
    used = sorted((r for r in srv if r["calls"]), key=lambda r: (-(r["input_tokens_est"] + r["result_tokens_est"]), r["server"]))
    return {"servers_used": [{k: r[k] for k in ("server", "calls", "errors", "context_share")} for r in used[:MCP_TOP]],
            "servers_called": len(used), "never_called": sorted(r["server"] for r in srv if r["never_called"]),
            "mcp_ctx_share_of_tools": round(sum(r["context_share"] for r in srv), 6)}


READOUTS = {"quality": lambda data, repos: readout_quality(data), "mcp": lambda data, repos: readout_mcp(data),
            "deployments": lambda data, repos: readout_deployments(data, len(repos)),
            "issues": lambda data, repos: readout_issues(data),
            "orchestration": lambda data, repos: json.load(open(os.path.join(data, "orchestration_summary.json")))["readout"],
            "context": lambda data, repos: json.load(open(os.path.join(data, "context.json")))["readout"],
            "orch_ux": lambda data, repos: load("orch_ux", "04-auto-analysis/orch-ux/orch_ux.py").readout(
                json.load(open(os.path.join(data, "orch_ux.json"))))}


def write_readout(data, section, value):
    """Update one section of readout.json, keep the others (so --only works)."""
    path = os.path.join(data, READOUT)
    ro = {}
    if os.path.exists(path):
        with open(path) as f:
            ro = json.load(f)
    ro.update({"v": 1, "generated": datetime.now(timezone.utc).strftime(ISO), section: value})
    os.makedirs(data, exist_ok=True)
    with open(path, "w") as f:
        json.dump(ro, f, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=DAYS)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--from", dest="start", choices=NAMES, help="start at this stage")
    g.add_argument("--only", choices=NAMES, help="run just this stage")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    ap.add_argument("--no-network", action="store_true", help="skip the network stages (deployments, issues)")
    a = ap.parse_args(argv)
    i = NAMES.index(a.only or a.start or NAMES[0])
    todo = STAGES[i:i + 1] if a.only else STAGES[i:]
    sys.path.insert(0, os.path.join(ROOT, "02-measure"))
    from schemas.config import load_config, data_dir
    cfg = load_config(None)
    data = data_dir(cfg)
    gh_checked = None
    for name, script, days, out, optional in todo:
        cmd = [sys.executable, os.path.join(ROOT, script)] + (["--days", str(a.days)] if days else [])
        repos = []
        if optional == "network":
            why = "network stages disabled" if a.no_network or not NETWORK else None
            repos = [] if why else repos_for(cfg, data)  # after impact2 has written impact.jsonl
            why = why or ("no repos" if not repos else None)
            if not why and not a.dry_run:
                gh_checked = gh_checked or [gh_problem()]
                why = gh_checked[0]
            if why:
                print(f"{'# ' if a.dry_run else ''}{name:8} skipped: {why}", flush=True)
                if not a.dry_run:
                    write_readout(data, name, {"skipped": why})
                continue
            cmd += [x for r in repos for x in ("--repo", r)]
        if a.dry_run:
            print(" ".join(cmd))
            continue
        t = time.time()
        p = subprocess.run(cmd, cwd=ROOT, stderr=subprocess.PIPE if optional else None, text=True)
        if optional and p.stderr:
            sys.stderr.write(p.stderr)
        print(f"{name:8} {time.time() - t:6.1f}s  exit {p.returncode}  {os.path.join(data, out)}", flush=True)
        if p.returncode and not optional:
            return p.returncode
        if not optional:
            continue
        if p.returncode:
            last = (p.stderr or "").strip().splitlines()
            ro = {"skipped": f"exit {p.returncode}" + (f": {last[-1]}" if last else "")}
        else:
            try:
                ro = READOUTS[name](data, repos)
            except Exception as e:  # missing or malformed output: say so, keep going
                ro = {"skipped": f"readout: {type(e).__name__}: {e}"}
        if "skipped" in ro:
            ro["skipped"] = ro["skipped"][:REASON_CHARS]
            print(f"{name:8} skipped: {ro['skipped']}", flush=True)
        write_readout(data, name, ro)
    return 0


if __name__ == "__main__":
    sys.exit(main())
