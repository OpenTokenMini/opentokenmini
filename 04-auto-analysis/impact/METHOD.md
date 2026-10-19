# impact: specs

Constants at the top of `impact.py`: `DAYS=30`, `PRE_MIN=5`, `POST_MIN=30`, `MIN_CALLS=10`, `WRITE_TOOLS`, `OUTSIDE_P=0.9`, `MIN_P=0.5`, `LINK_OPTION="yes"`, `AGENT_TRAILERS`; in `connectors.py`: `SCAN_MARGIN=1 day`, `DEFAULT_BRANCHES`.

## L-scan: commit metadata
Per repo, `git log --all --no-merges --numstat` from the earliest session start − `PRE_MIN` until now (author date, UTC; git `--since` gets `SCAN_MARGIN` extra because it filters on committer date). Kept per commit: sha, author ts, author email (output only as sha256[:12]), files, added, deleted (binary files count as a file with 0 lines), trailers, the sha named by `This reverts commit <sha>` in the body (nothing else of the body is kept), whether the sha is reachable from the default branch (`origin/HEAD`, else `main`, `master`, else `HEAD`). Commit subject: not used. `impact.read_subjects` is reserved: the connector reads it, but no output or schema field carries it, so it changes nothing. Merges excluded.

## L-repo: which sessions belong to a repo
Repos = `impact.repos` (if non-empty) else distinct `session.repo`. A session belongs to repo R when `realpath(session.repo) == R`, or `session.repo` is null and `session.project == basename(R)`. Sessions outside every repo are unlinked, except L-outside. `repo_label = basename(R)`.

## L-outside: sessions started outside any repo
Only when `impact.repos` is set: sessions with null `repo` (started in a parent dir such as `~/projects` and committing with `git -C`), or whose `repo` is a strict parent dir of R (nested repo, e.g. a session in `~/projects/know-how` committing to `know-how/opentokenmini/v002`), are also candidates for the L-trailer commits of R (never for L-window). If one wins L-assign it gets `link:"trailer"`, `link_p` = `OUTSIDE_P` (0.9: the trailer proves the harness, L-assign picks the session). Such a session can link to several repos; L-split shares its cost. Why: on real data 80% of Claude Code events had cwd `~/projects`, and the session driving v002 had repo `~/projects/know-how`.

## L-window: time window
Session window = [start − `PRE_MIN`, end + `POST_MIN`] (inclusive).

## L-trailer: agent trailer link (p = 1)
A trailer line matching an `AGENT_TRAILERS` regex (case-insensitive, first match) names a harness; `agent_trailer` = that harness id. A trailer commit can link only to sessions of that harness in the same repo whose window holds the commit ts (L-assign). Such a session gets `link:"trailer"`, `link_p:1.0`, and only its trailer commits.

## L-assign: one session per commit
Among eligible sessions (window holds the commit ts) the commit goes to the first by: sessions with ≥ `MIN_CALLS` API calls before smaller ones; sessions that used a `WRITE_TOOLS` tool (can edit files or run `git commit`, so shell tools count; decide `EDIT_TOOLS` is narrower on purpose, see decide/METHOD.md D-commit-link) before ones that did not; smallest distance (0 if ts in [start, end], else minutes to the nearer edge); most calls; latest start; session_id. A commit is never counted twice. Why: on real data many tiny automated sessions (`claude -p`, swarm helpers, 1 call, no tools) overlap the real one, and nearest-in-time gave them 17 v002 commits for $0.01. Sessions carry tool counts, not touched file paths, so "used a write tool" is the closest signal impact has to "touched the committed files".

## L-candidate: window candidates
Commits with no agent trailer whose author email is a `user.email` of the repo (local author) go, by L-assign, to sessions of any harness without a trailer link. Each such session gets one record `link:"window"`, `link_p:null` (pending). Non-local authors are ignored.

## L-subject: decision subject
`<session_id>:<sha256(",".join(sorted(commit shas)))[:8]>`. decide asks `commit_link` with this subject; a changed commit set yields a new subject, so stale answers never apply.

Contract impact<->decide (commit_link, single copy; decide/METHOD.md links here): subject = `<session_id>:<sha256(",".join(sorted(commit shas)))[:8]>` (impact `subject_of`, decide `link_subject`; repo_label is not used because one session can hold candidates in several repos); options = `decide/points.json` commit_link (`yes`/`no`); impact reads `probabilities.yes` (`LINK_OPTION`) of the latest decision per subject as link_p. Round trip: 04-auto-analysis/tests/test_impact.py test_roundtrip_decide.

## L-decided: applying commit_link
From `decisions.jsonl`, point `commit_link`, latest `ts` per subject wins; p = `probabilities[LINK_OPTION]` (missing → 0). p ≥ `MIN_P` → record kept with `link_p = p`; p < `MIN_P` → record dropped (session unlinked). No decision → stays pending (`link_p:null`).

## L-revert: reverts
Commit X is reverted when a scanned commit R (any time up to now, any ref) says it reverts a sha prefix of X; `X.reverted_by = R`. Per record: revert commits are neither kept nor reverted and add no lines; `added/deleted` = sum over non-revert commits; `commits_kept` = non-revert, not reverted; `commits_reverted` = non-revert, reverted.

## L-split: one session, several repos
A session's cost is split across its linked records by share of commits: record cost = session `cost.total` × len(record.commits) / Σ len(commits) over that session's linked records. So Σ `by_repo.cost` = Σ `by_harness.cost` = Σ cost of linked sessions (no double count).

## L-cost: summary
Only linked records (`link_p` non-null) count. Per group (repo_label, harness): `cost` = Σ record cost (L-split); `lines_added` = Σ max(0, record.added − added of its reverted commits); `cost_per_kept_commit = cost/commits_kept`, `cost_per_100_lines = 100·cost/lines_added`, `revert_rate = reverted/(kept+reverted)`; each null when its denominator is 0. `sessions_total` = sessions with end within `--days`; `unlinked_cost` = Σ cost of sessions not linked (pending included). Rounded to 6 decimals.

## L-ex: worked example (04-auto-analysis/tests/test_impact.py, fixtures/impact/sessions.jsonl)
Sessions a (claude-code 10:00–11:00, $2), b (codex 14:00–14:30, $1), c (claude-code 20:00–20:10, $0.50). Commits: c1 10:30 Claude trailer +10; c2 11:20 Claude trailer +5 (in POST_MIN); c3 13:00 Claude trailer +4 (no window); c4 14:10 local, no trailer +7; c5 14:20 other author +3; c6 16:00 reverts c2.
Pass 1: a = trailer, [c1, c2], added 15, kept 1, reverted 1; b = window, link_p null, [c4]. Summary: linked 1/3, by_repo cost 2.0, lines_added 10, cost_per_kept_commit 2.0, cost_per_100_lines 20.0, revert_rate 0.5, unlinked_cost 1.5.
Pass 2 with p(b)=0.8: linked 2, cost 3.0, lines_added 17, unlinked 0.5. With p(b)=0.3: b dropped, unlinked 1.5.
