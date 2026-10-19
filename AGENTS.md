# OpenTokenMini — agent entry point

Reference implementation that measures what AI agents cost and what they produce, across agents and models, then analyzes it. Every part is minimal, readable and replaceable: the user's own agent adapts it to their infrastructure. Each stage has a method (`METHOD.md`, what and why) separate from its implementation (one way to do it).

## Root causes

1. Base models have no internal representation of agentic workflows, the tools they run on, or what those tools can do. They can't estimate how many turns, tokens or minutes a task will take, and harness system prompts tell them not to try.
2. Their pretraining data predates the shift to agentic work, so they have no view of how it is done today.
3. Efficient delegation topologies and workflows are not in context. Some may not be known yet, and each operator rediscovers them alone.
4. No semi-automated feedback loop tells whether a workflow or a delegation actually worked.
5. Neither the orchestrating loop nor the human operator has tools to see cost, context and impact.

1 and 2 are on the labs' side. OpenTokenMini works on 3 to 5, in dependency order: visibility first, then the feedback loop, then measured topologies injected into the agent's context.

## Why it exists

In every harness, the human operator and the orchestrating agent work blind on cost, context and codebase impact. Delegation ends up either naive or quota-burning (for companies, tens of dollars per task), with no visibility and no granular control of the delegation topology.

One goal, two sides:
- Orchestrator: fewer tokens and less context overload at every level (main thread, subagents, task), and fewer runs stuck in local minima.
- Human: less cognitive load.

End goal: less time, the best translation of intent into the codebase, the fewest tokens, and a codebase that stays agent-maintainable, robust and correct. The means: explicit methodology; agent configurability (the orchestrator can define and customize analysis methods); codebase security; pick/route/judge decisions delegated to cheap decision models (jev-like, on-prem, open source); and fan-in maps, so the orchestrator does not have to read raw files.

Current models lack these workflows in pretraining but learn them well in-context. The tool's job is to measure, then inject that knowledge at decision points, so each operator does not have to reinvent it. Components are meant to be adapted to each environment. Each one states its trade-offs and leaves the important decisions to the human.

## Explaining the repo to the user (do this first)

If the user is getting familiar with the repo, explain the approach before touching anything, in the user's language, in this order:

1. Root causes: the five in [Root causes](#root-causes), and which ones this tool can act on.
2. The problem: teams spend heavily on AI agents without knowing on what, or whether it pays off.
3. Measure (`02-measure/`): each harness emits OpenTelemetry to a collector the user runs. Per API call: cost, tokens, latency, errors, retries, tool approvals. No prompts or code by default; full transcripts only if the owner opts in.
4. Analyze (`03-analyze/`): from cost per session up to cost per merged change, intent, MCP effectiveness and business impact.
5. Auto-analysis (`04-auto-analysis/`): small readers pull what happened in git, deployments, cloud logs, trackers and billing, joined with sessions by user, time and repo. Each is optional and independent.
6. Show: `05-dashboards/` for people, `06-optional/mcp-server/` for an orchestrator agent; decision models and corporate login also live in `06-optional/`. Same summary and outliers in both; recommendations backed by measured cases in `00-docs/use-case-reports/`.
7. Where data goes: only to infrastructure the user controls (`01-deploy/`). Every `AGENTS.md` states what data it touches.
8. What works today vs placeholder: see Status in `00-docs/agents/repo-map.md`. Say it plainly.

## Installing (guided, one step at a time)

The user pasted something like "clone this repo and follow AGENTS.md". There is no install script: you do each step, adapted to their setup. Before each step, tell the user in their language what it does, what data it touches, where that data goes and how to undo it, using the "Tell the user" lines below as the minimum. Wait for a yes. Never bundle two consents into one question. If a step depends on a placeholder, say so and skip it. Anything the user added to their prompt ("only Claude Code", "send it to Grafana") overrides these defaults.

1. Explain the approach (section above), then ask the scope: just them, a team, or a whole organization, and whether they already run an OpenTelemetry backend (Datadog, Grafana, an OTel collector).
2. Optional, read-only, no setup: past usage from local session logs of every installed harness (readers in `02-measure/readers/`, set by `readers.enabled`). `python3 02-measure/from-transcripts.py 30 > 00-docs/demo/usage.json`, then serve `00-docs/demo/` locally (e.g. `python3 -m http.server`) and give the user the URL.
   Tell the user: "Your coding agents keep session logs on this machine. I'll read token counts, models, tool names, project folders and timestamps from them to show your last 30 days. I won't read your prompts or code, and nothing leaves this machine."
3. Where the data goes: this machine (one person), a team server (VM or container they own, `01-deploy/`), or their existing backend. Follow the service section of `02-measure/AGENTS.md`.
   Tell the user: "From now on your agents can report each call as it happens. That data needs a place to go, and you choose it: this machine, a server your team owns, or a backend you already run. I'll set up only the one you pick."
4. Turn on telemetry in each harness on this machine: workstation section of `02-measure/AGENTS.md`, entries in `02-measure/harnesses.md`. Show the exact diff of each settings file.
   Tell the user: "I'm about to turn on telemetry in <harness>. From now on it will send metadata for every session and turn (tokens, cost estimate, model, latency, errors, which tools ran) to <endpoint>. It doesn't send prompts or code. This is the change to <file>; to undo it, delete these lines."
5. Verify: one short prompt per harness, then confirm records arrived.

Optional, each asked on its own, only after step 5 works:

- Link sessions to commits and pull requests (`04-auto-analysis/git.md`). Tell the user: "This reads git metadata from the repos you name (hashes, branches, line counts, merge status) to match sessions with the work they produced. No code is read."
- Full transcripts (`02-measure/transcripts.md`). Tell the user: "This sends the full text of sessions, including prompts, code and outputs, to <endpoint>. Only do this if whoever owns that data agreed to it."
- Token configs (`03-analyze/recommendations.md`). Tell the user: "These change how your agent behaves (model choice, context, effort) to spend less. I'll show each one and you can keep or drop it."
- More readers (`04-auto-analysis/`), dashboards (`05-dashboards/`), the MCP server for agents and corporate login (`06-optional/`).

Finish with a short report: what changed, in which files, where data goes, and how to undo each change.

## Running the code

Python 3, stdlib only. Run from the repo root.

- Collector (long-running): `python3 02-measure/collector/collector.py`, listens on `127.0.0.1:6979` (`OTM_PORT` or `collector.port`).
- Batch pipeline: `python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run]`. Stages, in order: normalize, readers, analyze, impact, decide, impact2.
- Config: copy `01-deploy/config.example.json` to `01-deploy/config.json` (gitignored), or set `OTM_CONFIG`. `null` = the constant at the top of the stage file.
- Data dir: `$OTM_DATA_DIR` > `data_dir` in config > `~/.local/share/opentokenmini`. Never inside the repo.
- Tests, one directory per stage: `for d in 0*/tests; do python3 -m unittest discover -s $d || break; done`. Shared fixtures are in `02-measure/tests/fixtures/`.
- Imports: numbered dirs are not importable packages. Each entry script and test finds the repo (`REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p/"02-measure"/"schemas").is_dir())`) and puts `02-measure/` on `sys.path`. Do the same in new files.
- Never delete files: move them to `todelete/` next to the file.

## Fixes found while installing

When the user hits an install or methodology problem and it gets fixed locally, ask whether the fix may apply to other setups too. If so, offer to open a pull request upstream to `OpenTokenMini/opentokenmini`. Only offer: never open one without an explicit yes. Repo-level acceptance criteria for such PRs are not defined yet.

## Index

Directories are numbered in install order; each has its own `AGENTS.md` and is the only place that describes its files.

- `00-docs/` notes for agents (`00-docs/agents/repo-map.md` has layout, rules and status), translations, the guided demo, measured use cases (cite only these for savings).
- `01-deploy/` where the service runs; `config.example.json` (shared config for all stages).
- `02-measure/` collector (`collector/`), transcript readers per harness (`readers/`), schemas and prices (`schemas/`), harness telemetry, past usage from local logs.
- `03-analyze/` method, summary and outliers (`analyze/`), recommendations, the batch `pipeline.py`.
- `04-auto-analysis/` one simple reader per system: git (`impact/`), deployments, cloud logs, trackers, billing, quality checks.
- `05-dashboards/` views for people: standalone (`standalone/`), or inside Datadog, Grafana or whatever the user already runs.
- `06-optional/` corporate login, MCP server for agents (`mcp-server/`), decision models (`decide/`).
