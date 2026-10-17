# MCP usage

Placeholder. Inventory of MCP servers each harness uses, and how their calls behave. Not to be confused with `../06-optional/mcp-server/`, which this project exposes.

- Reads: MCP server names and versions from harness configs; per-call tool name, latency, errors, retries from telemetry. Never the env vars or headers in those configs (they hold secrets).
- Configs: `~/.claude.json` and `.mcp.json`, `~/.codex/config.toml`, `~/.cursor/mcp.json`, VS Code `mcp.json`, Gemini `settings.json`.

## Flags

- high error or retry rate
- the same call repeated in a loop within a session
- outdated version, or docs servers returning stale content
- configured but never used (context cost with no benefit)

## Pitfalls

- Server names are user-defined; the same server appears under different names.
- Remote MCP servers rarely expose a version.
- Tool definitions cost context tokens on every request even when unused.
