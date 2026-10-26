# orchestration

Orchestration patterns from Claude Code transcripts, per delegating session (a session that launched at least one subagent): workers, launch batches, fan-out (most running at once), spawn depth, topology, orchestrator vs worker cost and models, worker peak context and duration, tokens each worker's result costs the launcher, oversized results, worker errors, batches followed by a commit. Reads usage blocks, `Agent`/`Task` tool_use and tool_result sizes, `<task-notification>` hand-backs, `git commit` in Bash commands and subagent `.meta.json`. Writes counts only: no prompt, result text or command. Specs and doc: `../orchestration.md` (O-*).

- Input: `~/.claude/projects/<project>/<session>.jsonl` + `<session>/subagents/**/agent-*.jsonl` (+ `.meta.json`) (or config `readers.paths.claude-code`, or `--root`); prices from `02-measure/schemas/prices.json`.
- Output in the data dir (or `--out`): `orchestration.jsonl` (one record per delegating session, with `worker_list`) and `orchestration_summary.json` (totals; `readout` copied by the pipeline into `readout.json` section `orchestration`, < 400 bytes).
- CLI: `python3 04-auto-analysis/orchestration/orchestration.py [--days N] [--root DIR] [--config PATH] [--out DIR]`
- Pipeline stage `orchestration` (local, optional) in `03-analyze/pipeline.py`. Tests: `../tests/test_orchestration.py`.

## Reconfigure
Constants at the top of `orchestration.py`: `DAYS`, `ROOT`, `AGENT_TOOLS`, `CHARS_PER_TOKEN`, `HUGE_RESULT_TOKENS`, `ERROR_STATUS`, `COMMIT_RX`, `DEEP_DEPTH`, `FANOUT_MIN`, `TOPOLOGIES`, `READOUT_BYTES`. Other harnesses are not read yet: add a `scan` returning the same per-session records.

## Adapt, trade-offs, decisions for the human

- Adapt: `HUGE_RESULT_TOKENS` to how much the orchestrator's context can absorb; `FANOUT_MIN` / `TOPOLOGIES` to the team's patterns.
- Trade-offs: costs are list-price estimates; result tokens are chars/4; teammates and workflow agents have no launch tool_use in the session, so they count as workers but stay unlinked (no batch, result size or error).
- Decisions for the human: cap worker result size (ask for short reports), pick cheaper worker models, limit fan-out, commit after each batch.
