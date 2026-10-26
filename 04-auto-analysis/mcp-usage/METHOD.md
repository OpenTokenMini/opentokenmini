# mcp-usage: specs

Constants at the top of `mcp_usage.py`: `DAYS=7`, `ROOT="~/.claude/projects"`, `CLAUDE_JSON="~/.claude.json"`, `CHARS_PER_TOKEN=4`, `IMAGE_TOKENS=1500`, `PREFIX="mcp__"`.

## M-name: server and tool
Claude Code names MCP tools `mcp__<server>__<tool>`, where `<server>` is the configured name with every char outside `[A-Za-z0-9_-]` replaced by `_` (`claude.ai Gmail` -> `claude_ai_Gmail`). Split at the first `__` after the prefix. Config and attachment names are normalized the same way so they join. Pitfall: a server name containing `__` splits wrong; the same server under two names counts twice.

## M-scan: what is read
Every `*.jsonl` under the root (subagent transcripts included, under their parent `sessionId`) whose mtime is at or after since, lines with `timestamp >= since` (since = now - `--days`). A `tool_use` block is one call, keyed by its id (repeated lines collapse). Its `tool_result` (same `tool_use_id`) gives size and error (`is_error: true`). A call with no result counts with result size 0 and no error. Unparseable lines are skipped.

## M-size: tokens
`input_tokens_est` = ceil(len(JSON of input) / `CHARS_PER_TOKEN`); `result_tokens_est` = same over the result text (string, or the sum of `text` blocks; `IMAGE_TOKENS` per image block; other blocks as JSON). Counted once per call, though the result stays in context for every later turn of the session (real cost is higher and grows with session length).

## M-agg: records
One record per server (`kind: "server"`, `tool: null`) and per called tool (`kind: "tool"`): `calls`, `errors`, token estimates, `sessions` (distinct session ids), `first`/`last` call (UTC). `context_share` = (input + result tokens) / the same sum over all tool calls in the window, MCP and built-in, so it reads as "share of tool context this server took". Sorted by server, server record first.

## M-config: configured servers
From `CLAUDE_JSON`: top-level `mcpServers` keys, each `projects.<path>.mcpServers` key, and `<path>/.mcp.json` `mcpServers` keys; `disabledMcpServers` and `disabledMcpjsonServers` names. `config` on server records: `disabled` if disabled in any project, else `enabled` if configured anywhere, else `none` (claude.ai connectors and plugins called but not in these files). Only names are read; values (commands, URLs, env, headers) never leave the function.

## M-loaded: available in a session
Servers named in `mcp_instructions_delta.addedNames` or as `mcp__` names in `deferred_tools_delta.addedNames` attachments; `loaded_sessions` = sessions where that happened. Servers whose tools sit in the system prompt (not deferred) and send no instructions leave no trace, so this undercounts.

## M-unused
`never_called` = server record with 0 calls in the window: configured or loaded, costing tool definitions in context, never used (flag "configured but never used" in `../mcp-usage.md`).

## M-ex: worked example (../tests/test_mcp_usage.py, ../tests/fixtures/mcp_usage/)
since 2026-10-01. Session s1: t0 `mcp__gh__search` on Sep 30 (dropped); t1 `mcp__gh__search` input 4 tok, result 400 chars = 100 tok; t2 `mcp__gh__get_issue` input 2, result 10, `is_error`; t3 `Bash` input 5, result 20; attachments load `docs server` and `gh`. Subagent of s2: t4 `mcp__claude_ai_Docs__read` input 1, one image result = 1500. Total tool context 1642. gh: 2 calls, 1 error, 116 tok, share 0.070646, config enabled, loaded 1. claude_ai_Docs: share 0.914129, config none. `docs_server` (project config, loaded), `unused-db` (project `.mcp.json`) and `claude_ai_Gmail` (disabled) never called.
