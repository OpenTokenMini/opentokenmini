# Repo map and editing rules

## Layout

Top-level directories are numbered in install order: `00-docs/`, `01-deploy/`, `02-measure/`, `03-analyze/`, `04-auto-analysis/`, `05-dashboards/`, `06-optional/`. `04-auto-analysis/` holds the readers that pull data from git, deployments, cloud logs and other systems into `02-measure/`'s records, one per system. `06-optional/` holds what only some setups need: corporate login, the MCP server for agents, decision models. Numbers are tentative; renumbering means renaming the directory and fixing links, which the docs build checks. Depth: at most three levels below the root (`<stage>/<component>/<file>`, e.g. `02-measure/collector/collector.py`, `02-measure/tests/fixtures/`). Test fixture trees under `tests/fixtures/` may go deeper (reader fixtures mirror each harness's own log layout). Components are subdirectories of a stage, each with `AGENTS.md` and `METHOD.md`; each stage keeps its tests and their fixtures in `<stage>/tests/`; reader and readout fixtures used by several stages live in `02-measure/tests/fixtures/`. Moved-out files go to `todelete/` next to them, never deleted; `todelete/` is gitignored. Each directory has an `AGENTS.md` that opens with what it does, its input, its output, and what data it touches; keep it accurate, nothing is hidden or obfuscated. Stages with a method keep it in `METHOD.md`, separate from the implementation. A piece becomes its own directory only when one file gets too big.

- `00-docs/agents/` technical notes for agents: this map, `orchestrate.md` (how a main session delegates to workers), `telemetry.md`, `coverage.md`.
- `00-docs/humans/` human pages: `landing.html` (served at `/`), logo, flow graph, share image. `<lang>/strings.json` is the phrase table per language (`es`, `zh`); `<lang>/README.md` is generated from it, never edited by hand.
- `00-docs/use-case-reports/` measured results from deployments, one file per case, any language, from `TEMPLATE.md`.
- `00-docs/demo/` the 30-day usage page from local session logs (`index.html` reads `usage.json`, falls back to `sample.json`).
- `00-docs/humans/` also holds the dashboard screenshots used by the READMEs (`dashboard.png`, `dashboard-individual.png`).
- The site: `opentokenmini.org` serves the landing, `/docs/` serves this repo (raw files plus one page per `.md`), `/llms.txt` indexes it for agents. Built by `.github/pages/build.py`.

## Section numbers

Used in the checklist and diagrams; the first digit is the directory number.

- 1 Deploy: 1.1 host, 1.2 auth, 1.3 storage, 1.4 checklist
- 2 Measure: 2.1 collector, 2.2 harnesses, 2.3 transcripts, 2.4 intent labels, 2.5 adoption
- 3 Analyze: 3.1 levels, 3.2 summary and outliers, 3.3 recommendations
- 4 Auto-analysis: 4.1 git, 4.2 deployments, 4.3 issue trackers, 4.4 billing, 4.5 cloud logs, 4.6 MCP usage, 4.7 docs, 4.8 chat usage, 4.9 quality, 4.10 context, 4.11 orchestration
- 5 Dashboards: 5.1 standalone, 5.2 inside the user's monitoring (Datadog, Grafana)
- 6 Optional: 6.1 MCP server, 6.2 identity, 6.3 decision models

## Rules

- Placeholders share one shape: what it reads, coverage (first, next, long tail), workflow, pitfalls.
- Code for what must give the same number everywhere (collector, schemas, metrics, outliers, MCP tools); specs for what touches each org's infra (integrations, deploy, vendors).

- Agent-facing content (`AGENTS.md`, `METHOD.md`, `00-docs/agents/`, code comments): English only.
- Human-facing content (landing, READMEs, dashboard UI): `en`, `zh`, `es`. Edit English only, then run `python3 .github/pages/i18n.py`: it lists new phrases with an empty translation in each `strings.json`; fill them in and rerun. The build fails if a generated README is out of date and shows English for any empty phrase.
- Root stays clean: `AGENTS.md`, `README.md`, `LICENSE` and the pipeline directories. `.github/` publishes the site (build, translations, docs viewer, `llms.txt` header, workflow).
- No savings figure in any doc unless it comes from a report in `00-docs/use-case-reports/`.

## Status

- Working (unit-tested): collector and normalizer (`02-measure/collector/`, port 6979, `/health`); telemetry coverage vs transcripts (`02-measure/coverage.py`); transcript readers for Claude Code, Codex, Antigravity, OpenCode and Pi (`02-measure/readers/`); schemas and prices (`02-measure/schemas/`); analyze with metric catalog and outliers (`03-analyze/analyze/`); batch `03-analyze/pipeline.py`; commit impact from local git (`04-auto-analysis/impact/`); readers for GitHub Actions (`04-auto-analysis/deployments/`) and GitHub Issues/PRs (`04-auto-analysis/issues/`), both pipeline stages writing `readout.json`; readers for MCP usage (`04-auto-analysis/mcp-usage/`), quality (`04-auto-analysis/quality/`), orchestration (`04-auto-analysis/orchestration/`) and context efficiency (`04-auto-analysis/context/`) from Claude Code transcripts, local pipeline stages writing `readout.json`; decision points with jev (`06-optional/decide/`); MCP server (`06-optional/mcp-server/`), including `live.py` for orchestrators (overview, session, agents, node, who_touches, declare, method, record); standalone dashboard, redesigned, reads `readout.json` (`05-dashboards/standalone/`); live view on collector + transcripts, with per-session delegation view (`05-dashboards/live/`, port 7845).
- Draft: `00-docs/demo/` 30-day usage page with real usage data (not linked from the README yet).
- Drafted: OTel telemetry for harnesses other than Claude Code, token configs, deploy options, d1 connector (untested).
- Placeholder: transcripts push, storage, integrations other than local git, GitHub Actions, GitHub Issues/PRs and Claude Code transcripts, other decision-model vendors, dashboards inside the user's monitoring, dashboard i18n.
