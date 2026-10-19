# dashboard

DRAFT, to be redesigned: too dense and too granular for people. Keep it working, but don't build on its layout.

Static page for people: spend, cost mix, models, projects, tools, MCP servers, sessions, outliers and recommendations with their decisions, commit impact, coverage. Vanilla JS in one `index.html`, no CDN, no build. Computes no new numbers; harness filter only sums rows already split by harness (header cost/calls/sessions from `by.harness`; cost mix, models, projects, tools are not split by harness and stay unfiltered).

Header: three numbers only: spend, top harness cost, $/kept commit (from impact by_harness; tooltip gives linked cost and sessions). Calls/sessions/turns live in Coverage and Metrics.

Input (relative fetch from `?src=DIR/`, default `data/`): `analysis.decided.json` if present, else `analysis.json`; `impact_summary.json`; `decisions.jsonl`; `sessions.jsonl` (optional; `repo` is never shown). Each missing file only hides its panels and shows red in the status bar. Output: none. Data touched: read only.

## Run

```
python3 05-dashboards/standalone/serve.py [--data DIR] [--port 7840]      # dev helper: / = page, /data/ = the 5 page inputs only (DATA_FILES; events/ and otel/ are never served), POST /console
python3 05-dashboards/standalone/serve.py --data 02-measure/tests/fixtures/readouts   # fixture
```

Data dir default: `--data` > `$OTM_DATA_DIR` > `~/.local/share/opentokenmini`. Binds 127.0.0.1. Any static server works too, e.g. from the repo root `python3 -m http.server 7841` and open `/05-dashboards/standalone/?src=../../02-measure/tests/fixtures/readouts/`. Opening the file directly (`file://`) cannot fetch data.

Telemetry: only under `serve.py` (it sends header `X-OTM-Dev`), the page appends console errors/warnings, uncaught errors, rejections, long tasks (> `LONG_TASK_MS`) and slow frames (> `SLOW_FRAME_MS`) to `/tmp/otm-dashboard-console.jsonl` (`LOG` in serve.py), plus one `load` event listing the files found. Read that file instead of opening devtools. Missing optional files appear as 404s in the browser network log, not in this log.

Tests: `05-dashboards/tests/test_dashboard.py` (serve.py endpoints; page script run against a stub DOM by `05-dashboards/tests/fixtures/dashboard/smoke.js` when `node` is installed, on the fixture and on an empty dir).

## Reconfigure

No config keys: the page reads files only. Point it elsewhere with `?src=` (any URL prefix the browser can fetch, same origin unless CORS allows). Tunables are constants at the top of the script: `LIST_MAX` (rows before "view more"), `CHART_H`, `LONG_TASK_MS`, `SLOW_FRAME_MS`, `FILES` (file names tried per input, first found wins), colors. UI strings are in the `S` table.

Decisions are attached by `subject`: outliers match `<metric>:<group>:<session_id>`, then `<metric>:<group>`, then `<session_id>`; recommendations match `<id>` or `recommendation:<id>`. Latest matching decision wins. All decisions also appear in the Decisions panel.

Example, show 10 rows per list and read a shared folder: set `const LIST_MAX = 10;` and open `/?src=/shared/otm/`.

## Adapt, trade-offs, decisions for the human

- Adapt: point `?src=` at wherever the outputs live, or rebuild the views in the team's existing tool (`../AGENTS.md`).
- Trade-offs: one static file, no build, no dependencies; it computes no numbers, so it never disagrees with the analysis but cannot show anything the analysis did not write.
- Decisions for the human: what the redesigned page should show first, and for whom (developer, team lead, budget owner).
