# mcp-usage

Reads Claude Code session transcripts and MCP configs and reports, per MCP server and per tool: calls, errors, estimated tokens of call inputs and results, their share of all tool context, sessions using it, and servers configured or loaded but never called. Reads from transcripts only the `tool_use` / `tool_result` blocks (sizes, error flag, tool name, session id, timestamp) and the `mcp_instructions_delta` / `deferred_tools_delta` attachments (server and tool names); from configs only server names and disabled lists, never commands, URLs, env or headers. Stores no content. Specs: `METHOD.md` (M-*). Placeholder spec and coverage: `../mcp-usage.md`.

- Input: `~/.claude/projects/**/*.jsonl` (or config `readers.paths.claude-code`, or `--root`); `~/.claude.json` (user and per-project `mcpServers`, `disabledMcpServers`, `disabledMcpjsonServers`) and `.mcp.json` in each project listed there.
- Output: `mcp_usage.jsonl` in the data dir (or `--out`): one `kind: "server"` record per server, then one `kind: "tool"` record per called tool; a one-line summary on stdout (top 3 servers by context tokens).
- CLI: `python3 04-auto-analysis/mcp-usage/mcp_usage.py [--days N] [--root DIR] [--claude-json FILE] [--config PATH] [--out DIR]`
- Pipeline stage `mcp` (local, optional) in `03-analyze/pipeline.py`; its summary goes to section `mcp` of `readout.json`. Record schema draft: `../tests/fixtures/mcp_usage/mcp_usage.schema.json` (to promote to `02-measure/schemas/` once the fields settle).

## Reconfigure
Constants at the top of `mcp_usage.py`: `DAYS`, `ROOT`, `CLAUDE_JSON`, `CHARS_PER_TOKEN`, `IMAGE_TOKENS`. Other harnesses (Codex, Cursor, VS Code, Gemini, OTel `tool_result` events) are not read yet; add a `scan` returning the same `(uses, results, loaded)` triple.

## Adapt, trade-offs, decisions for the human

- Adapt: `CHARS_PER_TOKEN` for code-heavy or non-English results; `--days`.
- Trade-offs: token counts are estimates from characters, not tokenizer counts; a result is counted once although it stays in context for every later turn (M-size). Tool definition cost of unused servers is not estimated, only flagged (`never_called`). Servers loaded without deferred tools leave no trace in transcripts, so `loaded_sessions` undercounts.
- Decisions for the human: whether to disable servers flagged `never_called`.
