# Repo map and editing rules

## Layout

Top-level directories follow the pipeline: `measure/` → `integrations/` → `analyze/` → `dashboard/` and `mcp-server/`, plus `deploy/` and `docs/`. At most two levels. Each directory has an `AGENTS.md` that opens with what it does, its input, its output, and what data it touches; keep it accurate, nothing is hidden or obfuscated. Stages with a method keep it in `METHOD.md`, separate from the implementation. A piece becomes its own directory only when one file gets too big.

- `docs/agents/` technical notes for agents.
- `docs/humans/<lang>/README.md` translations of the root `README.md` (`zh`, `es`). Frozen: out of date with the current layout until the owner approves the English version; then re-translate.
- `docs/use-case-reports/` measured results from deployments, one file per case, any language, from `TEMPLATE.md`.
- `docs/demo/` walkthrough with screenshots, once dashboard mockups exist.
- `docs/humans/dashboard.png` dashboard screenshot used by every README (pending).

## Section numbers

Tentative, used in the checklist and diagrams; directories stay unnumbered.

- 1 Deploy: 1.1 host, 1.2 auth, 1.3 storage, 1.4 checklist
- 2 Measure: 2.1 collector, 2.2 harnesses, 2.3 transcripts, 2.4 intent labels, 2.5 adoption
- 3 Integrate: 3.1 version control, 3.2 CI, 3.3 issue trackers, 3.4 billing, 3.5 observability, 3.6 MCP usage, 3.7 docs, 3.8 identity, 3.9 chat usage
- 4 Analyze: 4.1 levels, 4.2 summary and outliers, 4.3 decision models, 4.4 quality, 4.5 recommendations
- 5 Readout: 5.1 dashboard, 5.2 MCP server

## Rules

- Placeholders share one shape: what it reads, coverage (first, next, long tail), workflow, pitfalls.
- Code for what must give the same number everywhere (collector, schemas, metrics, outliers, MCP tools); specs for what touches each org's infra (integrations, deploy, vendors).

- Agent-facing content (`AGENTS.md`, `METHOD.md`, `docs/agents/`, code comments): English only.
- Human-facing content (READMEs, dashboard UI): `en`, `zh`, `es`. While translations are frozen, edit English only.
- Root stays clean: `AGENTS.md`, `README.md`, `LICENSE` and the pipeline directories. `.github/` publishes the docs site (viewer, `llms.txt` header, workflow).
- No savings figure in any doc unless it comes from a report in `docs/use-case-reports/`.

## Status

- Working: Claude Code → `measure/collector.py` → embedded dashboard; past Claude Code usage via `measure/from-transcripts.py`.
- Draft: `docs/demo/` guided walkthrough with real usage data (not published yet).
- Drafted: other harnesses, token configs, deploy options.
- Placeholder: transcripts push, storage, all integrations, analyze and its output, decision models, quality checks, metric catalog, standalone dashboard, MCP server, demo, dashboard i18n.
