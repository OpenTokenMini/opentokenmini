# Orchestration

First reader working: [`orchestration/`](orchestration/AGENTS.md) (Claude Code transcripts). How sessions delegate to subagents, what the workers cost, and how much their results weigh on the orchestrator.

- Reads: subagent transcripts and `.meta.json`, `Agent`/`Task` launches, their results and `<task-notification>` hand-backs, per-call usage, `git commit` in Bash. Never prompt, result or command text in the output.
- Used for: how much spend goes to workers, whether fan-out pays off, which workers flood the orchestrator's context, whether batches end in commits.

## Flags

- worker results above 2000 tokens (the orchestrator carries them on every later turn)
- workers on the most expensive model for small tasks
- wide fan-out without a commit after the batch
- failed or killed workers

## Pitfalls

- Teammates and workflow agents have no launch in the session transcript: counted, not linked.
- Result tokens are chars/4 estimates; usage and cost are from logged usage at list price.
- Other harnesses (Codex, OpenCode) log subagents differently; not read yet.

## Specs (O-*)

Constants at the top of `orchestration.py`: `DAYS=7`, `AGENT_TOOLS=(Agent, Task)`, `CHARS_PER_TOKEN=4`, `HUGE_RESULT_TOKENS=2000`, `DEEP_DEPTH=2`, `FANOUT_MIN=3`, `READOUT_BYTES=400`.

- **O-sessions**: a session is `<project>/<sid>.jsonl` plus every `<project>/<sid>/subagents/**/agent-<id>.jsonl` (workflow agents under `workflows/wf_*/`). Kept if it has a subagent file and any of its files was modified since the window start; a session with no worker is not a record.
- **O-scan**: per transcript, `user`/`assistant`/`attachment` lines with a timestamp. Usage dedups by message id (lines of one message repeat it); first and last timestamp give the span.
- **O-launch**: a `tool_use` named in `AGENT_TOOLS` is a launch; launches in one assistant message (one turn) form a batch.
- **O-link**: a worker's `.meta.json` `toolUseId` is matched to the transcript holding that launch (orchestrator or another worker); that transcript is its launcher. Depth = `spawnDepth` (default 1). Unmatched workers stay unlinked.
- **O-result**: tokens a worker costs its launcher = its `tool_result` content plus every `<task-notification>` (user string or `queued_command` attachment prompt) naming its `<tool-use-id>`, chars/4.
- **O-huge**: an orchestrator-launched worker with result tokens > `HUGE_RESULT_TOKENS`.
- **O-error**: `is_error` on the result, `toolUseResult.status` or a notification `<status>` in `ERROR_STATUS` (failed, killed, error, cancelled).
- **O-commit**: a batch is committed when one of its workers ran `git [-C dir] commit`, or the orchestrator did between the batch start and the next batch.
- **O-fanout**: `max_batch` = most workers in one batch; `max_concurrent` = most depth-1 workers whose [launch, last line] spans overlap; `parallel_share` = share of depth-1 workers overlapping another.
- **O-cost**: cost per message via `schemas/cost.py`; orchestrator cost = session file, worker cost = subagent files, split by model family. Peak ctx = max(input + cache read + cache write) of one call.
- **O-topology**: first match of deep (depth >= 2), single-helper (1 worker), fan-out (max_concurrent or max_batch >= 3), serial (max_concurrent <= 1), small-parallel.
- **O-summary**: totals over sessions: topologies, cost split and by model, max concurrent, worker peak ctx and duration percentiles, result tokens p50/p90 (orchestrator-launched), huge, batches committed, errors, unlinked.
- **O-readout**: summary subset plus up to 3 findings (biggest result absorber, top worker model share, batches then commit), findings dropped from the end until the JSON is < `READOUT_BYTES`.
