# OpenTokenMini — agent entry point

Reference implementation that measures what AI agents cost and what they produce, across agents and models, then analyzes it. Every part is minimal, readable and replaceable: the user's own agent adapts it to their infrastructure. Each stage has a method (`METHOD.md`, what and why) separate from its implementation (one way to do it).

## Explaining the repo to the user (do this first)

If the user is getting familiar with the repo, explain the approach before touching anything, in the user's language, in this order:

1. The problem: teams spend heavily on AI agents without knowing on what, or whether it pays off.
2. Measure (`measure/`): each harness emits OpenTelemetry to a collector the user runs. Per API call: cost, tokens, latency, errors, retries, tool approvals. No prompts or code by default; full transcripts only if the owner opts in.
3. Integrate (`integrations/`): sessions are joined with version control, issue trackers, docs, MCP servers, observability and identity, by user, time and repo.
4. Analyze (`analyze/`): from cost per session up to cost per merged change, intent, MCP effectiveness and business impact. Optional decision models classify events cheaply; optional quality checks (security, performance, usability).
5. Show: `dashboard/` for people, `mcp-server/` for an orchestrator agent. Same summary and outliers in both; recommendations backed by measured cases in `docs/use-case-reports/`.
6. Where data goes: only to infrastructure the user controls (`deploy/`). Every `AGENTS.md` states what data it touches.
7. What works today vs placeholder: see Status in `docs/agents/repo-map.md`. Say it plainly.

## Installing (guided, one step at a time)

The user pasted something like "clone this repo and follow AGENTS.md". There is no install script: you do each step, adapted to their setup. Before each step, tell the user in their language what it does, what data it touches, where that data goes and how to undo it, using the "Tell the user" lines below as the minimum. Wait for a yes. Never bundle two consents into one question. If a step depends on a placeholder, say so and skip it. Anything the user added to their prompt ("only Claude Code", "send it to Grafana") overrides these defaults.

1. Explain the approach (section above), then ask the scope: just them, a team, or a whole organization, and whether they already run an OpenTelemetry backend (Datadog, Grafana, an OTel collector).
2. Optional, read-only, no setup: past usage from local session logs. `python3 measure/from-transcripts.py 30 > usage.json`, then show `docs/demo/index.html` with it. Claude Code only for now.
   Tell the user: "Claude Code keeps session logs on this machine. I'll read token counts, models, tool names, project folders and timestamps from them to show your last 30 days. I won't read your prompts or code, and nothing leaves this machine."
3. Where the data goes: this machine (one person), a team server (VM or container they own, `deploy/`), or their existing backend. Follow the service section of `measure/AGENTS.md`.
   Tell the user: "From now on your agents can report each call as it happens. That data needs a place to go, and you choose it: this machine, a server your team owns, or a backend you already run. I'll set up only the one you pick."
4. Turn on telemetry in each harness on this machine: workstation section of `measure/AGENTS.md`, entries in `measure/harnesses.md`. Show the exact diff of each settings file.
   Tell the user: "I'm about to turn on telemetry in <harness>. From now on it will send metadata for every session and turn (tokens, cost estimate, model, latency, errors, which tools ran) to <endpoint>. It doesn't send prompts or code. This is the change to <file>; to undo it, delete these lines."
5. Verify: one short prompt per harness, then confirm records arrived.

Optional, each asked on its own, only after step 5 works:

- Link sessions to commits and pull requests (`integrations/version-control.md`). Tell the user: "This reads git metadata from the repos you name (hashes, branches, line counts, merge status) to match sessions with the work they produced. No code is read."
- Full transcripts (`measure/transcripts.md`). Tell the user: "This sends the full text of sessions, including prompts, code and outputs, to <endpoint>. Only do this if whoever owns that data agreed to it."
- Token configs (`analyze/recommendations.md`). Tell the user: "These change how your agent behaves (model choice, context, effort) to spend less. I'll show each one and you can keep or drop it."
- Other integrations (`integrations/`), the dashboard (`dashboard/`), the MCP server for agents (`mcp-server/`).

Finish with a short report: what changed, in which files, where data goes, and how to undo each change.

## Index

- `measure/` collector, harness telemetry, transcripts, past usage from local logs.
- `integrations/` one file per kind of external system.
- `analyze/` method, decision models, quality checks, recommendations.
- `dashboard/` views and metric catalog.
- `mcp-server/` the same analysis as MCP tools for agents.
- `deploy/` where the service runs.
- `docs/agents/repo-map.md` layout, editing rules, status.
- `docs/agents/coverage.md` what each part must cover first, one table.
- `docs/agents/telemetry.md` what OTel adds over transcripts, pitfalls.
- `docs/use-case-reports/` measured results; cite only these for savings.
