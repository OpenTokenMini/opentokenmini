# deployments

Reads CI runs (GitHub Actions through the `gh` CLI) and joins each run to the agent session whose commit it tested, using `impact.jsonl`. Reads run metadata only: workflow, trigger event, head sha and branch, status, conclusion, timestamps, and for failed runs the name of the failed job and step. No logs, no commit subjects, no actor. Specs: `METHOD.md` (D-*). Placeholder spec and coverage: `../deployments.md`.

- Input: `gh run list` / `gh run view --json jobs` per repo (uses the user's existing `gh auth`, read-only calls); `impact.jsonl` from the data dir.
- Output: `deployments.jsonl` in the data dir (or `--out`), one record per run; a one-line summary on stdout (failure rate for agent-linked runs vs the repo baseline).
- CLI: `python3 04-auto-analysis/deployments/deployments.py [--repo PATH|OWNER/NAME ...] [--days N] [--ci NAME] [--config PATH] [--impact FILE] [--out DIR]`
- Pipeline stage `deployments` of `03-analyze/pipeline.py` (after `impact2`, skipped without network or `gh`); its summary goes to section `deployments` of `readout.json` (`../../03-analyze/output.md`). Standalone, run it after `impact` (it only joins linked impact records).
- Record schema: `02-measure/schemas/deployment.schema.json`.

## Reconfigure
Repos: `--repo` (repeatable; a local path gives `repo_label` = basename, same as impact; `OWNER/NAME` gives `NAME`), else config `impact.repos`, else the current dir. CI connectors: dict `CI` in `deployments.py`: `github_actions` (gh CLI), `gitlab_ci` (placeholder, raises). Add one with signature `fetch(repo, since, run) -> list[dict]` returning the run dicts described in METHOD.md D-scan.

## Adapt, trade-offs, decisions for the human

- Adapt: the repos list; `MAX_RUNS` for busy repos; a GitLab connector.
- Trade-offs: a run links only through its head commit, so in a push of several commits only the tip's session is credited (D-join). Pending impact window candidates are not joined until decide confirms them.
- Decisions for the human: whether workflow step names (which can contain the command a step runs) may be stored; which repos may be queried.
