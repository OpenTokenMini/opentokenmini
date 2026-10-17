# mcp-server

Placeholder. MCP server so an orchestrator agent can read the analysis, get outliers, and ask where spend is going. The agent-facing twin of `../dashboard/`.

- Input: `../analyze/output.md` (summary and outliers).
- Output: MCP tools, read-only.
- Data it touches: the same aggregates the dashboard shows, under the same access rules (`../integrations/identity.md`).

## Tools (draft)

- `summary(period, group_by)` the configured metrics.
- `outliers(since)` new outliers with their evidence.
- `metric(name, filters)` one metric sliced.
- `adoption(group_by)` who has telemetry on vs the directory, per harness and group.
- `checklist()` deployment items: done, missing, worth adding.
- `session(id)` metadata of one session, never content unless the measure level includes it.

## Pitfalls

- MCP is pull: outliers reach the agent when it asks. For push, a webhook to chat or a scheduled agent run that calls `outliers`.
- Results must fit in context: aggregates and pagination, never raw records.
- No tool writes or changes anything; recommendations are text for the agent to propose to a person.
