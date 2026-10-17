# integrations

Placeholder. Connectors to the systems a session touches, so `../analyze/` can join them with sessions. One file per kind of system; each lists coverage (first, next, long tail), workflow and pitfalls.

- Input: the external system's API or local files.
- Output: records keyed by user, time and repo or project.
- Data it touches: metadata only by default (who, when, what changed, status), never content unless the owner enables it. Each file states exactly what it reads. Credentials are read-only.

| File | Systems (first) | Used for |
|---|---|---|
| `version-control.md` | GitHub, GitLab | spend per merged change |
| `ci.md` | GitHub Actions, GitLab CI | do agent changes pass; headless agent runs |
| `issue-trackers.md` | Jira, GitHub Issues, Linear | intent and business impact |
| `billing.md` | Anthropic, OpenAI, cloud billing, seats | real spend vs telemetry estimate |
| `observability.md` | Datadog, Grafana, OTel backends | infra and service impact |
| `mcp-usage.md` | harness MCP configs and call telemetry | MCP effectiveness |
| `docs.md` | Confluence, Notion, Google Docs, repos | non-technical users, org visibility |
| `identity.md` | Okta, Entra ID, Google Workspace | login, user to team mapping |
| `chat-usage.md` | ChatGPT, Claude, Gemini, M365 Copilot | non-technical users |
