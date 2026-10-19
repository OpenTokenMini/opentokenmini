"""Shared helpers for the transcript readers. Specs R-* in readers/METHOD.md."""
import json, os, sys, time
from datetime import datetime, timezone

import pathlib  # numbered stage dirs aren't importable: find the repo, put 02-measure/ on sys.path
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.cost import load_prices, make_tokens, event_cost, zero_tokens, zero_cost

HOME = os.path.expanduser("~")
SCRATCH_DIRS = ("tmp",)  # first path component (after $HOME) that labels a project "(scratch)"
PRICES = load_prices()
_repos = {}


def root(cfg, harness, default):
    """R-paths: readers.paths.<harness> overrides the reader's default root."""
    return os.path.expanduser((cfg.get("readers", {}).get("paths") or {}).get(harness) or default)


def recent(path, since):
    """Cheap prefilter: a file not modified since `since` holds no newer record."""
    try:
        return os.path.getmtime(path) >= since.timestamp()
    except OSError:
        return False


def jsonl(path):
    with open(path, errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                pass


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_ok(ts, since):
    """R-window: keep records with ts >= since (ISO strings, UTC)."""
    if not ts:
        return False
    if ts.endswith("Z"):  # fast path: same-format UTC strings compare lexically
        return ts >= since.strftime("%Y-%m-%dT%H:%M:%S")
    return parse_ts(ts) >= since


def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def project(cwd):
    """R-project: short label from the working dir, never the full path."""
    parts = [p for p in (cwd or "").replace("file://", "").replace(HOME, "").split("/") if p]
    if not parts:
        return "(unknown)"
    if parts[0] in SCRATCH_DIRS:
        return "(scratch)"
    return "/".join(parts[-2:]) if parts[0] == "projects" and len(parts) > 2 else parts[-1]


def repo(cwd):
    """R-repo: nearest ancestor of cwd containing .git, else None. Cached per cwd."""
    cwd = (cwd or "").replace("file://", "")
    if not cwd:
        return None
    if cwd not in _repos:
        d = cwd
        while d and d != "/" and not is_git(d):
            d = os.path.dirname(d)
        _repos[cwd] = home_rel(d) if d and d != "/" else None
    return _repos[cwd]


def is_git(d):
    """R-repo: a .git file (worktree) or a .git dir with HEAD; an empty .git dir is not a repo."""
    g = os.path.join(d, ".git")
    return os.path.isfile(g) or os.path.isfile(os.path.join(g, "HEAD"))


def home_rel(path):
    """R-repo: $HOME prefix -> `~` so events carry no user name; consumers expanduser."""
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def event(kind, ts, harness, session_id, cwd=None, request_id=None, parent=None, subagent=False,
          model=None, provider=None, tokens=None, reported=None, reported_total=None,
          duration_ms=None, error=None, tools=(), agent_type=None):
    """One event (schemas/event.schema.json). Cost via schemas C-cost; prompts carry zero tokens and no text."""
    if kind == "api_call":
        tokens = tokens or zero_tokens()
        cost, basis = event_cost(tokens, model, PRICES, reported=reported, reported_total=reported_total)
    else:
        tokens, cost, basis = zero_tokens(), zero_cost(), "unknown"
    return {"v": 1, "kind": kind, "ts": ts, "harness": harness, "source": "transcript",
            "session_id": str(session_id), "request_id": request_id, "parent_session_id": parent,
            "subagent": bool(subagent), "user": None, "project": project(cwd), "repo": repo(cwd),
            "model": model, "provider": provider, "tokens": tokens, "cost": cost, "cost_basis": basis,
            "duration_ms": duration_ms, "error": error, "retries": 0, "tools": sorted(t for t in tools if t),
            "tool": None, "decision": None, "decision_source": None,
            **({"agent_type": agent_type} if agent_type else {})}  # optional, only when known (R-claude-agent-type)
