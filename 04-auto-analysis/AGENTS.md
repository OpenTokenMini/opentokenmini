# auto-analysis

Placeholder. One reader per system a session touches (git, deployments, cloud logs, trackers, billing), each simple and independent. They pull what happened there into records next to `../02-measure/`'s, so `../03-analyze/` can join them with sessions. Each file lists coverage (first, next, long tail), workflow and pitfalls.

- Input: the external system's API or local files.
- Output: records keyed by user, time and repo or project.
- Data it touches: metadata only by default (who, when, what changed, status), never content unless the owner enables it. Each file states exactly what it reads. Credentials are read-only.

| File | Systems (first) | Used for |
|---|---|---|
| `git.md` | GitHub, GitLab | spend per merged change |
| `deployments.md` | GitHub Actions, GitLab CI | do agent changes pass; headless agent runs |
| `issue-trackers.md` | Jira, GitHub Issues, Linear | intent and business impact |
| `billing.md` | Anthropic, OpenAI, cloud billing, seats | real spend vs telemetry estimate |
| `cloud-logs.md` | Datadog, Grafana, OTel backends | infra and service impact |
| `mcp-usage.md` | harness MCP configs and call telemetry | MCP effectiveness |
| `docs.md` | Confluence, Notion, Google Docs, repos | non-technical users, org visibility |
| `chat-usage.md` | ChatGPT, Claude, Gemini, M365 Copilot | non-technical users |
| `quality.md` | linters, scanners, benchmarks | security, performance, usability of agent changes |

Corporate login and user to team mapping: `../06-optional/identity.md`.
