# issues

Links GitHub issues and pull requests to commits and, through `impact.jsonl`, to agent sessions; puts session cost next to each PR, issue and ticket type. First working reader of `../issue-trackers.md` (GitHub Issues). Reads metadata only through `gh api graphql` (read-only); PR titles and branch names are parsed for ticket keys and then dropped, bodies and comments are never read. Specs: `METHOD.md` (I-*).

- Input: local clones with a GitHub `origin` (`--repo`, repeatable); GitHub via the `gh` CLI (must be authenticated: `gh auth status`); `impact.jsonl` and `sessions.jsonl` from the data dir.
- Output: `issues.jsonl` (one record per PR and per issue), `issues_summary.json` in the data dir (or `--out`).
- CLI: `python3 04-auto-analysis/issues/issues.py --repo PATH [--repo PATH ...] [--days N] [--config PATH] [--out DIR] [--impact FILE] [--sessions FILE]`
- Data touched: PR and issue number, state, state reason, timestamps, labels, commit shas, merge sha, closing-issue numbers, author login (output only as sha256[:12]). No network beyond `gh`; no writes to GitHub.
- Pipeline stage `issues` of `03-analyze/pipeline.py` (after `deployments`, skipped without network or `gh`); its summary goes to section `issues` of `readout.json` (`../../03-analyze/output.md`). Standalone, run after `impact` (it joins on impact's linked commits).
- Record schema: `02-measure/schemas/issue.schema.json` (`v: 1`, ISO UTC, `hash12` authors, `repo_label` = basename of the repo as in impact).

Tests: `../tests/test_issues.py` (fake `gh`, fixtures in `../tests/fixtures/issues/`, no network).

## Reconfigure

Constants at the top of `issues.py`: `DAYS`, `PAGE`, `MAX_PAGES`, `PR_COMMITS`, `TYPE_LABELS`, `KEY_RX`, `REF_RX`, `BRANCH_RX`. No config key yet (adding one means adding `issues` to `DEFAULTS` in `02-measure/schemas/config.py`).

## Adapt, trade-offs, decisions for the human

- Adapt: `TYPE_LABELS` to the repo's label names; `KEY_RX` to the team's Jira/Linear key convention; `MAX_PAGES` for busy repos (`issues_summary.truncated` lists repos that hit it).
- Trade-offs: a PR joins a session only through commits impact already linked (trailer, or window confirmed by decide); PRs whose commits were rebased or squashed remotely join only if the merge sha was pulled and linked. Cost is split by commit share, so a session is never counted twice.
- Decisions for the human: which repos may be read; whether label-derived types are good enough or a tracker (Jira, Linear) should be the source of ticket type.
