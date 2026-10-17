# OpenTokenMini — agent entry point

Reference implementation that measures what coding agents cost and what they produce, across agents and models, then analyzes it. Every part is minimal, readable and replaceable: the user's own agent adapts it to their infrastructure. Each stage has a method (`METHOD.md`, what and why) separate from its implementation (one way to do it).

## Explaining the repo to the user (do this first)

If the user is getting familiar with the repo, explain the approach before touching anything, in the user's language, in this order:

1. The problem: teams spend heavily on coding agents without knowing on what, or whether it pays off.
2. Measure (`measure/`): each harness emits OpenTelemetry to a collector the user runs. Per API call: cost, tokens, latency, errors, retries, tool approvals. No prompts or code by default; full transcripts only if the owner opts in.
3. Integrate (`integrations/`): sessions are joined with version control, issue trackers, docs, MCP servers, observability and identity, by user, time and repo.
4. Analyze (`analyze/`): from cost per session up to cost per merged change, intent, MCP effectiveness and business impact. Optional decision models classify events cheaply; optional quality checks (security, performance, usability).
5. Show: `dashboard/` for people, `mcp-server/` for an orchestrator agent. Same summary and outliers in both; recommendations backed by measured cases in `docs/use-case-reports/`.
6. Where data goes: only to infrastructure the user controls (`deploy/`). Every `AGENTS.md` states what data it touches.
7. What works today vs placeholder: see Status in `docs/agents/repo-map.md`. Say it plainly.

## Installing

Installs are done by the user's own agent following these files, not by scripts:

- Try locally (Claude Code only): `python3 measure/collector.py`, then run `measure/claude-code-with-telemetry` instead of `claude`. Dashboard at http://127.0.0.1:7811 ; records in `/tmp/claude-otel.jsonl` 
- Team: `measure/AGENTS.md`, service section first (data owner), then workstation section on each machine.

## Index

- `measure/` collector, harness telemetry, transcripts.
- `integrations/` one file per kind of external system.
- `analyze/` method, decision models, quality checks, recommendations.
- `dashboard/` views and metric catalog.
- `mcp-server/` the same analysis as MCP tools for agents.
- `deploy/` where the service runs.
- `docs/agents/repo-map.md` layout, editing rules, status.
- `docs/agents/coverage.md` what each part must cover first, one table.
- `docs/agents/telemetry.md` what OTel adds over transcripts, pitfalls.
- `docs/use-case-reports/` measured results; cite only these for savings.
