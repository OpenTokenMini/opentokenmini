# Analysis output

Placeholder. The one output of `analyze/`, read by both `../05-dashboards/` (people) and `../06-optional/mcp-server/` (agents). Same numbers in both.

## Summary

- Configurable per deployment: which metrics (from `../05-dashboards/metrics.md`), period, grouping (team, repo, model, harness, intent).
- Each value carries its definition, period, sample size and the session ids behind it.

## Outliers

- Per metric and group, compared against that group's own baseline (robust z-score or percentile; thresholds as named constants).
- Each outlier: metric, group, value, baseline, sample size, top contributing sessions.
- Examples: a session 10x the team's median spend, an MCP server whose error rate jumped, a repo where spend per merged change doubled.

## Pipeline readout (`readout.json`)

Written by `pipeline.py` in the data dir after each optional stage: the local readers `quality`, `mcp`, `orchestration` and `context`, then the network stages `deployments` and `issues` (all run after `impact2`). One section per stage; a run updates only the stages it ran, so `--only` keeps the other sections. Schema not yet in `../02-measure/schemas/`.

- Top level: `v` (1), `generated` (ISO UTC), `quality`, `mcp`, `orchestration`, `context`, `deployments`, `issues`.
- A skipped stage is `{"skipped": reason}`. Network stages are skipped before running with reason `network stages disabled` (`NETWORK = False` or `--no-network`), `gh not found`, `gh not authenticated` or `no repos`; nothing is fetched then and the stage's previous `.jsonl` is left as it was. Any optional stage that fails is skipped after running, and the pipeline goes on: `exit N: <last stderr line>` when the script exits nonzero, `readout: <error>` when its output cannot be read. Reasons are cut to `REASON_CHARS` (200).
- `quality` (from `quality_summary.json`, Q-summary in `../04-auto-analysis/quality/METHOD.md`; field names as the reader writes them; Claude Code transcripts only, last `--days`):
  - `sessions`: sessions with at least one tool call or result.
  - `tool_error_rate`: tool results flagged as errors / tool calls (6 decimals, null with no calls).
  - `test_runs`: shell commands matching the reader's `TEST_RX`; `test_fail_rate`: runs that errored or whose output matched `FAIL_RX` / `test_runs` (null with no runs).
  - `commits`: commits impact linked to these sessions (from `impact.jsonl`; 0 when impact has not run or linked nothing).
  - `commits_without_test`: linked commits whose session ran no test at or before the commit.
  - `risky`: `{destructive, exfiltration, secrets}`, counts of shell commands matching each class regex (`RISK_RX`; exfiltration to localhost does not count). Counts to look at, not verdicts.
  - `file_rework_rate`: files a session edited that a different session edited again within `REWORK_HOURS` / files edited.
  - `commit_rework_rate`: linked commits followed within `REWORK_HOURS` by another commit touching one of the same files / linked commits found in git log. File-level, so an upper bound: high in repos where every commit touches the same file (e.g. `AGENTS.md`).
- `mcp` (from the server records of `mcp_usage.jsonl`, M-agg in `../04-auto-analysis/mcp-usage/METHOD.md`; Claude Code transcripts and `~/.claude.json` / `.mcp.json` server names):
  - `servers_used`: up to `MCP_TOP` (5) servers with calls, most estimated context tokens (call inputs + results) first, each `{server, calls, errors, context_share}`; `context_share` = that server's estimated tokens / all tool calls' (MCP and built-in), 6 decimals.
  - `servers_called`: servers with at least one call (`servers_used` may be truncated).
  - `never_called`: names of servers configured or loaded but never called (all of them, sorted; normalized as in tool names).
  - `mcp_ctx_share_of_tools`: sum of `context_share` over all servers, the MCP part of tool context. Token counts are character estimates; a result counts once although it stays in context.
- `orchestration` (the `readout` of `orchestration_summary.json`, O-readout in `../04-auto-analysis/orchestration.md`; Claude Code sessions that launched subagents): `sessions`, `workers`, `topologies`, `worker_cost_share`, `max_concurrent`, `worker_peak_ctx_p90`, `result_tokens_p90`, `huge_results`, `worker_errors`, up to 3 `findings`; under 400 bytes.
- `context` (the `readout` of `context.json`, X-readout in `../04-auto-analysis/context/METHOD.md`; Claude Code transcripts): `sessions`, `peak_p50`, `over_150k`, `over_250k`, `compactions`, `cache_read_share`, `cache_write_usd`, `reread_tok`, up to 3 `findings`, `detail`; under 400 bytes.
- `deployments` (from `deployments.jsonl`, rates by `deployments.rates`, D-rate in `../04-auto-analysis/deployments/METHOD.md`): `repos` queried, `runs`, `runs_linked` (head commit linked to a session), `agent` and `baseline` each `{failure_rate, n}`; `n` counts completed pass/fail runs only, `failure_rate` is null when `n` is 0.
- `issues` (from `issues_summary.json`, I-summary in `../04-auto-analysis/issues/METHOD.md`): `repos` scanned, `prs`, `prs_merged`, `prs_linked` (PRs with at least one session), `ticketless_share` (PRs with no closing issue and no ticket key / `prs`, 4 decimals, null with no PRs), `cost_linked` ($ of session cost on PRs, split by commit share), `issues`, `issues_closed_without_pr`, `truncated` (repo:kind that hit `MAX_PAGES`).
- Repos: config `impact.repos`, else the git toplevels of sessions that impact linked, most linked first, at most `MAX_REPOS`.

## Adoption and checklist

- Adoption inventory (`../02-measure/adoption.md`) and deployment checklist state (`../01-deploy/checklist.md`) are part of the output, so operator and agent see the same thing.

## Pitfalls

- Small groups give noisy baselines: below a minimum sample size, report but do not flag.
- Weekly cycles and holidays: compare like with like.
- Per-person outliers follow the privacy defaults in `../02-measure/METHOD.md`.
