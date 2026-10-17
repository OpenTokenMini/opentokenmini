# Repo map and editing rules

## Layout

Top-level directories are numbered in install order: `00-docs/`, `01-deploy/`, `02-measure/`, `03-analyze/`, `04-auto-analysis/`, `05-dashboards/`, `06-optional/`. `04-auto-analysis/` holds the readers that pull data from git, deployments, cloud logs and other systems into `02-measure/`'s records, one per system. `06-optional/` holds what only some setups need: corporate login, the MCP server for agents, decision models. Numbers are tentative; renumbering means renaming the directory and fixing links, which the docs build checks. At most two levels. Each directory has an `AGENTS.md` that opens with what it does, its input, its output, and what data it touches; keep it accurate, nothing is hidden or obfuscated. Stages with a method keep it in `METHOD.md`, separate from the implementation. A piece becomes its own directory only when one file gets too big.

- `00-docs/agents/` technical notes for agents.
- `00-docs/humans/<lang>/README.md` translations of the root `README.md` (`zh`, `es`). Frozen: out of date with the current layout until the owner approves the English version; then re-translate.
- `00-docs/use-case-reports/` measured results from deployments, one file per case, any language, from `TEMPLATE.md`.
- `00-docs/demo/` walkthrough with screenshots, once dashboard mockups exist.
- `00-docs/humans/` will also hold the dashboard screenshot used by every README (pending).

## Section numbers

Used in the checklist and diagrams; the first digit is the directory number.

- 1 Deploy: 1.1 host, 1.2 auth, 1.3 storage, 1.4 checklist
- 2 Measure: 2.1 collector, 2.2 harnesses, 2.3 transcripts, 2.4 intent labels, 2.5 adoption
- 3 Analyze: 3.1 levels, 3.2 summary and outliers, 3.3 recommendations
- 4 Auto-analysis: 4.1 git, 4.2 deployments, 4.3 issue trackers, 4.4 billing, 4.5 cloud logs, 4.6 MCP usage, 4.7 docs, 4.8 chat usage, 4.9 quality
- 5 Dashboards: 5.1 standalone, 5.2 inside the user's monitoring (Datadog, Grafana)
- 6 Optional: 6.1 MCP server, 6.2 identity, 6.3 decision models

## Rules

- Placeholders share one shape: what it reads, coverage (first, next, long tail), workflow, pitfalls.
- Code for what must give the same number everywhere (collector, schemas, metrics, outliers, MCP tools); specs for what touches each org's infra (integrations, deploy, vendors).

- Agent-facing content (`AGENTS.md`, `METHOD.md`, `00-docs/agents/`, code comments): English only.
- Human-facing content (READMEs, dashboard UI): `en`, `zh`, `es`. While translations are frozen, edit English only.
- Root stays clean: `AGENTS.md`, `README.md`, `LICENSE` and the pipeline directories. `.github/` publishes the docs site (viewer, `llms.txt` header, workflow).
- No savings figure in any doc unless it comes from a report in `00-docs/use-case-reports/`.

## Status

- Working: Claude Code → `02-measure/collector.py` → embedded dashboard; past Claude Code usage via `02-measure/from-transcripts.py`.
- Draft: `00-docs/demo/` guided walkthrough with real usage data (not published yet).
- Drafted: other harnesses, token configs, deploy options.
- Placeholder: transcripts push, storage, all integrations, analyze and its output, decision models, quality checks, metric catalog, standalone dashboard, MCP server, demo, dashboard i18n.
