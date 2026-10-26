"""impact vcs connectors: name -> commits(repo, since, until, cfg) -> list of commit dicts.

Commit dict (metadata only, see METHOD.md L-scan):
  {sha, ts (ISO UTC), email, local: bool (author email is a configured user.email of the repo),
   files, added, deleted, trailers: [str], reverts: sha|None, on_default_branch: bool,
   subject: str|None (only when cfg impact.read_subjects)}
"""
import re, subprocess
from datetime import datetime, timedelta, timezone

SCAN_MARGIN = timedelta(days=1)  # git --since filters on committer date; author ts is filtered exactly afterwards
DEFAULT_BRANCHES = ("main", "master")
REVERT_RX = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
FMT = "%x1e%H%x1f%aI%x1f%ae%x1f%(trailers:unfold,separator=%x1d)%x1f%s%x1f%b%x1f"


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False).stdout


def _utc(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_branch(repo):
    ref = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD").strip()
    if ref:
        return ref
    for b in DEFAULT_BRANCHES:
        if _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}").strip():
            return b
    return "HEAD"


def local_git(repo, since, until, cfg):
    """All non-merge commits on any ref with author ts in [since, until] (datetimes, UTC)."""
    git_since = f"--since={(since - SCAN_MARGIN).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    on_default = set(_git(repo, "rev-list", default_branch(repo), git_since).split())
    mine = {e.strip().lower() for e in _git(repo, "config", "--get-all", "user.email").splitlines() if e.strip()}
    out = _git(repo, "log", "--all", "--no-merges", "--numstat", f"--format={FMT}", git_since)
    lo, hi = since.strftime("%Y-%m-%dT%H:%M:%SZ"), until.strftime("%Y-%m-%dT%H:%M:%SZ")
    read_subjects = bool(cfg.get("impact", {}).get("read_subjects"))
    commits = []
    for chunk in out.split("\x1e")[1:]:
        sha, ts, email, trailers, subject, body, numstat = chunk.split("\x1f", 6)
        ts = _utc(ts)
        if not lo <= ts <= hi:
            continue
        added = deleted = files = 0
        for line in numstat.strip().splitlines():
            a, d, _ = line.split("\t", 2)
            files += 1
            added += int(a) if a.isdigit() else 0  # binary files report "-"
            deleted += int(d) if d.isdigit() else 0
        m = REVERT_RX.search(body)
        commits.append({"sha": sha, "ts": ts, "email": email.lower(), "local": email.lower() in mine,
                        "files": files, "added": added,
                        "deleted": deleted, "trailers": [t for t in trailers.split("\x1d") if t.strip()],
                        "reverts": m.group(1) if m else None, "on_default_branch": sha in on_default,
                        "subject": subject if read_subjects else None})
    return commits


def github_api(repo, since, until, cfg):
    raise NotImplementedError("github_api: placeholder; list commits via the REST API and return the same dicts as local_git")


VCS = {"local_git": local_git, "github_api": github_api}
