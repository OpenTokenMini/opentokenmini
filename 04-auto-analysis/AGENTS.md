# auto-analysis

The subdirectories work (`impact/`, `deployments/`, `issues/`, `mcp-usage/`, `quality/`, `context/`, `orchestration/`); the `.md` files without one are placeholders. One reader per system a session touches (git, deployments, cloud logs, trackers, billing), each simple and independent. They pull what happened there into records next to `../02-measure/`'s, so `../03-analyze/` can join them with sessions. Each file lists coverage (first, next, long tail), workflow and pitfalls.

- Input: the external system's API or local files.
- Output: records keyed by user, time and repo or project.
- Data it touches: metadata only by default (who, when, what changed, status), never content unless the owner enables it. Each file states exactly what it reads. Credentials are read-only.

| File | Systems (first) | Used for |
|---|---|---|
| `impact/` | local git | links sessions to commits; cost per kept and reverted commit |
| `git.md` | GitHub, GitLab | spend per merged change |
| `deployments/` | GitHub Actions (gh CLI) | CI runs joined to sessions by head commit; agent vs baseline failure rate |
| `deployments.md` | GitHub Actions, GitLab CI | do agent changes pass; headless agent runs |
| `issues/` | GitHub Issues/PRs (gh) | links PRs and issues to sessions via impact commits; spend per ticket type |
| `mcp-usage/` | Claude Code transcripts, ~/.claude.json/.mcp.json | calls, errors, context share per MCP server/tool; configured but never called |
| `quality/` | Claude Code transcripts, local git | risky commands, test pass/fail, tool errors, rework per session and commit |
| `context/` | Claude Code transcripts | context growth, peaks, compactions, cache mix and cost, re-reads, biggest tool outputs |
| `orchestration/` | Claude Code transcripts (subagents, task notifications) | delegating sessions: topology, fan-out, worker vs orchestrator cost, result tokens handed back, errors, commits per batch |
| `issue-trackers.md` | Jira, GitHub Issues, Linear | intent and business impact |
| `billing.md` | Anthropic, OpenAI, cloud billing, seats | real spend vs telemetry estimate |
| `cloud-logs.md` | Datadog, Grafana, OTel backends | infra and service impact |
| `mcp-usage.md` | harness MCP configs and call telemetry | MCP effectiveness |
| `docs.md` | Confluence, Notion, Google Docs, repos | non-technical users, org visibility |
| `chat-usage.md` | ChatGPT, Claude, Gemini, M365 Copilot | non-technical users |
| `quality.md` | linters, scanners, benchmarks | security, performance, usability of agent changes |
| `context.md` | Claude Code transcripts | context efficiency: flags and pitfalls |
| `orchestration.md` | Claude Code transcripts | delegation: flags, method (O-* IDs) |

Tests for every subdirectory: `tests/`. `impact` runs in `../03-analyze/pipeline.py`, and so do `quality`, `mcp-usage` (stage `mcp`), `orchestration`, `context`, `deployments` and `issues` as optional stages writing `readout.json`.

Corporate login and user to team mapping: `../06-optional/identity.md`.
