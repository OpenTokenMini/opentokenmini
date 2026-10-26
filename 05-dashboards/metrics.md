# Metrics

Placeholder catalog. Each metric: name, definition, source, level from `../03-analyze/METHOD.md`. Deployments copy this file and edit it.

| Metric | Definition | Source |
|---|---|---|
| Spend | USD per day, by user, team, model | measure |
| Spend per merged change | USD of sessions linked to a merged PR / count | measure + version control |
| Cache hit rate | cache read tokens / input tokens | measure |
| Retries | API errors with retry attempts per session | measure |
| Human approvals | tool decisions needing a person / all tool decisions | measure |
| MCP waste | MCP calls that errored or repeated / all MCP calls | measure + mcp |
