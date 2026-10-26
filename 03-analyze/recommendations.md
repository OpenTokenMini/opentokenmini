# Recommendations

Changes to suggest once the data shows where spend goes. Each entry states the change, what it saves, and the use case report that measured it. No figure without a report in `../00-docs/use-case-reports/`.

## Harness token configs (opt-in, they change agent behavior)

Candidates, not yet measured:

- shorter default replies (output is the largest share of spend)
- keep long sessions instead of restarting (cache writes cost ~40x a cached read)
- delegate only large tasks to subagents
- model per task (small model for search and trivial work)

## Other candidates

- update or remove MCP servers that send agents into loops
- model per intent, from intent labels
