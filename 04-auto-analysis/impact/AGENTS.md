# impact

Links agent sessions to the git commits they produced and puts cost next to kept and reverted work. Reads git metadata only (no diffs, no file contents). Specs: `METHOD.md` (L-*).

- Input: `sessions.jsonl` (analyze), `decisions.jsonl` (decide, optional) from the data dir; git repos on disk.
- Output: `impact.jsonl`, `impact_summary.json` in the data dir (or `--out`).
- CLI: `python3 04-auto-analysis/impact/impact.py [--days N] [--harness ID] [--config PATH] [--out DIR] [--sessions FILE] [--decisions FILE]`
- Two passes: run 1 writes trailer links and window candidates (`link_p: null`); decide asks `commit_link` per candidate (subject per L-subject); run 2 applies the answers (L-decided).

## Reconfigure
Config key `impact`: `vcs` (connector name, default `local_git`), `repos` (list of repo paths to scan instead of `session.repo`), `read_subjects` (bool, default false).

Connectors live in `impact/connectors.py`, dict `VCS`: `local_git` (git CLI), `github_api` (placeholder, raises). Add one with signature `commits(repo, since, until, cfg) -> list[dict]` returning the commit dicts described at the top of `connectors.py`, and register it in `VCS`.

Example: scan two repos even when sessions lack a repo path:
```json
{"impact": {"vcs": "local_git", "repos": ["~/code/app", "~/code/lib"], "read_subjects": false}}
```

## Adapt, trade-offs, decisions for the human

- Adapt: `impact.repos` to the repos the team works in; a VCS connector for a hosted API instead of local git (`github_api` is a placeholder).
- Trade-offs: trailer links are exact but need harnesses that write trailers; time-window links catch more commits but are guesses until decide confirms them (`commit_link`). Commit subjects are not used; `read_subjects` is reserved and changes nothing yet (METHOD.md).
- Decisions for the human: which repos may be scanned; whether $/kept commit is a fair measure for this team.
