# readers: method

Turns each harness's local session logs into `event` records (schemas/event.schema.json, `source: "transcript"`).
Token normalization and cost come from schemas (C-tokens, C-cost, C-cache-ttl); this file covers only what the readers decide.
Tests: `02-measure/tests/test_readers.py` (synthetic fixtures in `02-measure/tests/fixtures/readers/`, sqlite dbs built in a temp dir).

## Common rules

R-paths. Each reader has a default root (constant `ROOT`/`ROOTS` at the top of its file). `readers.paths.<harness>` in config replaces it; `~` is expanded. Antigravity also reads `conversation_metadata.json` from the overridden dir instead of `~/.gemini/...` (so tests never touch the real home).

R-window. `since = now - --days` (UTC). A record is kept when `ts >= since`. Files with mtime < since are skipped without opening. `Z` timestamps compare as strings; others are parsed (unparseable -> dropped).

R-project. Label from cwd: strip `file://` and `$HOME`, split on `/`. Empty -> `(unknown)`; first part in `SCRATCH_DIRS` (`tmp`) -> `(scratch)`; under `projects/` with depth > 2 -> last two parts; else last part. Example: `/home/user/projects/demo/app` -> `demo/app` (test_claude).

R-repo. Nearest ancestor of cwd that is a git repo (`.git` file, or `.git/HEAD` exists; an empty `.git` dir does not count), else null. `$HOME` prefix written as `~` (no user name in events; consumers `expanduser`). Cached per cwd. It is a local path; consumers must not publish it.

R-privacy. No prompt text, tool arguments or outputs are copied. `user_prompt` events carry only ts/session/project with zero tokens. Test: fixtures contain `LEAKCANARY` and `/home/user/models`; neither may appear in the output (test_no_leak).

R-isolate. Each harness runs in its own try; an exception sets `summary[h].error = "<Type>: <msg>"` and the other harnesses still run. The summary always has `events, calls, cost, unpriced_calls, error` per harness (`unpriced_calls` = calls with `cost_basis "unknown"`).

R-output. `<data dir>/events/transcript.jsonl`, sorted by (ts, harness, session_id), written to `.tmp` then renamed. With `--harness`, lines of the other harnesses already in the file are kept as-is. `--out DIR` replaces the data dir.

Fields every reader leaves fixed: `user` null (no harness logs it), `retries` 0, `tool`/`decision`/`decision_source` null.

## Claude Code (`~/.claude/projects/**/*.jsonl`)

R-claude-dedup. One call per `requestId` (fallback `message.id`). A streamed response writes several lines with the same id; usage is taken from the last line (its counts are final), tools are the union of `tool_use` block names. Model `<synthetic>` (`SKIP_MODELS`) is not an API call. `isApiErrorMessage` -> `error: "api_error"`. `isSidechain` -> `subagent: true`.
Example: req_1 has lines with output 3 then 250 -> one call, output 250, tools `["Bash"]`.

R-claude-agent-type. A subagent transcript `<session>/subagents/agent-<id>.jsonl` has `agent-<id>.meta.json` next to it; its `agentType` (e.g. `Explore`, `general-purpose`) goes to the optional event field `agent_type` on that file's api_calls. Missing or unreadable meta -> field absent.

R-claude-ttl. `usage.cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` go to `cache_write_5m` / `cache_write_1h` (C-cache-ttl prices each at its own rate; 1h writes cost 2x input instead of 1.25x).
Example (claude-sonnet-4-6: input 3, output 15, cache_read 0.3, 5m 3.75, 1h 6 USD/Mtok): input 1000, output 250, cache_read 10000, writes 1500 (5m) + 500 (1h) -> 0.003 + 0.00375 + 0.003 + 0.005625 + 0.003 = $0.018375 (without the split, all 2000 at 3.75: $0.01725).

R-claude-truncated. A call where no line carries `message.stop_reason` was cut off mid-stream (seen: 139 of ~25.6k calls in 30 days, output ~5 tokens). It gets `error: "truncated"` (unless already `api_error`); tokens are kept as logged and the call still counts in calls/cost. Example: req_2 -> `"truncated"`, req_1/req_3 -> null.

R-claude-prompt. A human turn = a `user` line, not `isMeta`, not `isSidechain`, whose content is a string or has a `text` block (tool results are not prompts). Example fixture has 3 user lines, 1 prompt.

Unknown model (example `claude-mystery-1`) -> `cost_basis "unknown"`, total 0 (C-cost).

## Codex (`~/.codex/sessions/**/rollout-*.jsonl`)

R-codex-delta. `token_count` events hold cumulative `total_token_usage`; per call = current total minus previous total. A negative delta (counter reset) falls back to that event's `last_token_usage`. `input_tokens` includes cached input and `output_tokens` includes reasoning (`input_includes_cache`, `output_includes_reasoning`). `request_id` is null (not logged).
R-codex-repeat. A `token_count` whose total equals the previous total is a repeat, not a call.
Subagent: `session_meta.source.subagent.thread_spawn.parent_thread_id` -> `parent_session_id`, `subagent: true`.
Example: totals (input 1000 incl. 600 cached, output 100 incl. 20 reasoning), the same total again, an `info: null` event, then (2500, 1600, 300, 50) -> calls {input 400, cache_read 600, output 80, reasoning 20} $0.001575 and {input 500, cache_read 1000, output 170, reasoning 30} $0.00275; parent `cx-0` (test_codex).

## OpenCode (`~/.local/share/opencode/opencode.db`)

R-opencode-ro. Opened as `file:...?mode=ro&immutable=1`: a live WAL db is never locked or written.
R-opencode-empty. Assistant messages with zero tokens and no error are skipped; zero-token messages with an error (e.g. `MessageAbortedError`) are kept as error calls (this is why counts can exceed the public script by a few).
R-opencode-cost. `cost > 0` -> passed as `reported_total` (C-cost allocates it by list-price shares, basis `reported_total_allocated`); 0 -> list price. Reasoning is separate from output. `duration_ms = time.completed - time.created` when completed >= created.
Example: input 7898, output 13, reasoning 53, cache_read 64, cost 0.0247032, 4 s -> basis `reported_total_allocated`, total 0.0247032, duration 4000, tools `["bash"]`.

## Pi (`$PI_CODING_AGENT_DIR` or `~/.pi/agent`, `sessions/<cwd>/*.jsonl`)

R-pi-calls. Each assistant message with `usage` is one call; output includes reasoning.
R-pi-cost. When `usage.cost.total > 0`, the per-type USD (`input, output, cacheRead, cacheWrite`) is passed as `reported` (basis `reported`); else list price. Local gguf models have no price -> `unknown`.
Example: output 75 incl. reasoning 28, reported total $0.01644125 -> basis `reported`; model `Qwen3.5-0.8B-BF16.gguf` -> `unknown`.

## Antigravity (`~/.gemini/antigravity-cli/conversations/*.db`, `~/.gemini/antigravity/conversations/*.db`)

Rows are protobuf; parsed with a stdlib wire-format reader using field numbers from the descriptors in the agy binary (see docstrings in antigravity.py). Reasoning = usage field 9, included in output. Tool calls attach to the last call of the conversation.
R-agy-coverage. A db or conversation that fails to parse is skipped and recorded in `antigravity.coverage[path] = reason`; the summary gets `skipped` and the first reason as `error`.
Example: gemini-3-flash, input 1000, output 100, cache_read 4000 -> (1000x0.5 + 100x3 + 4000x0.05)/1e6 = $0.001, tools `["run_command"]`, coverage empty.

## Validation against real data (2026-10-18)

30 days, same moment as the public `from-transcripts.py`: Claude 25411 calls vs 25410, codex 1137 = 1137, pi = public, opencode 38 vs 35 (R-opencode-empty). With R-claude-ttl, Claude cost is ~3.7% above public (public prices every write at 5m rate); val-measure recomputed $1187.51 for its window. Later run (16:45Z): 25597 calls, $1195.02, 139 truncated; `schemas/check.py` ok.
