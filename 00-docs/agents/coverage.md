# Coverage

What each part must support first. Priorities are tentative planning, not measured market share; revise with real deployments.

| Part | First | Next | Long tail / fallback |
|---|---|---|---|
| Harnesses | Claude Code, Codex CLI, Gemini CLI (native OTel) | GitHub Copilot, Cursor (admin APIs) | session logs or LLM gateway |
| Storage | JSONL + DuckDB/SQLite | Postgres | ClickHouse, existing OTel backend |
| Deploy | local, Docker Compose on a VM | AWS/GCP/Azure containers | Kubernetes Helm, existing backend |
| Version control | GitHub, GitLab | Bitbucket, Azure DevOps | local `git log` |
| CI | GitHub Actions, GitLab CI | Jenkins, CircleCI, Buildkite | none |
| Issue trackers | Jira, GitHub Issues, Linear | Azure Boards, GitLab Issues | keys parsed from branches and PRs |
| Billing | Anthropic, OpenAI APIs | Bedrock, Vertex, Azure OpenAI | seat count times price |
| Observability | Datadog, Grafana, OTel Collector | New Relic, Elastic, Honeycomb, Splunk, cloud-native | deploy markers only |
| Docs | Confluence, Notion, Google Docs, repo markdown | SharePoint | GitBook, Slab, Coda |
| Identity | Okta, Entra ID, Google Workspace | generic OIDC/SAML | CSV alias table |
| Chat usage | ChatGPT, Claude, Gemini, M365 Copilot exports | | |
| Decision models | d1 (local) | jev, Cloudflare clef | any LLM |
| Readout | dashboard, MCP server | Datadog/Grafana dashboards | |
