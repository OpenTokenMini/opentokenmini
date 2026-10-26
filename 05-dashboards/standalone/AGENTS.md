# dashboard

DRAFT: redesigned for progressive disclosure (dark UI, one header, five cards, detail on click); not yet on the `../reference/` layout.

Static page for people. Vanilla JS in one `index.html`, no CDN, no build. Computes no new numbers; the harness filter only sums rows already split by harness (cost mix, models, projects, tools are not split and stay unfiltered).

Header: title, period, harness filter, then at most five cards: spend, $/kept commit (the delivery card: below the value one dim line `CI fail <agent> vs <baseline> · PRs <linked>/<total>` when those readout sections exist; with no impact file the card shows the CI or PR outcome instead), sessions, to review (outliers + recommendations), sources (harnesses with events / total). The overview below shows only spend by day; a card click opens its detail (`DETAIL` in the script): spend (day chart, cost mix, models, projects), impact (by repo, by harness, CI failure rate agent vs baseline, pull requests: PRs linked, merged, ticketless share, $ linked, closed without PR; by ticket type), sessions (sessions, tools, MCP servers), to review (outliers, recommendations, decisions), sources (coverage, metrics). Lists show `LIST_MAX` rows plus "view more"; secondary numbers (z, n, evidence, all decision probabilities, cost basis) are tooltips. The header shows the data age (`updated 3h ago`, red past `STALE_H`); the delivery card line starts with `linked <n>/<total>` sessions, since $/kept commit only covers linked sessions. Outliers show metric names and units from `analysis.metrics`. Readout sections without a panel (any key other than `v`, `generated`, `deployments`, `issues`, e.g. `quality`, `mcp`, `context`) appear in the overview as small cards, one row per key (rate/share as %, cost as $, lists as counts with the items as tooltip). Full lists are built only on "view more". `sessions.jsonl` and `decisions.jsonl` (the large files) are fetched after the first render. Esc closes the open detail. Status bar: files found (green, size as tooltip), loading (dim) or missing (red), generated time, color legends, and a notes button that opens the legend text.

Input (relative fetch from `?src=DIR/`, default `data/`): `analysis.decided.json` if present, else `analysis.json`; `impact_summary.json`; `decisions.jsonl`; `sessions.jsonl` (optional; `repo` is never shown); delivery, optional: `readout.json` (sections `deployments` and `issues`, contract in `../../03-analyze/output.md`; a section that is `{"skipped": reason}` or absent is hidden, other sections render as generic cards) and `issues_summary.json` (only its `by_type`, which the readout lacks). Delivery is not split by harness. Missing or skipped delivery input: its card line and panels are hidden (the card too with no impact file) and it is not listed in the status bar. Each missing file (other than the delivery ones) only hides its panels and shows red in the status bar. Output: none. Data touched: read only.

## Run

```
python3 05-dashboards/standalone/serve.py [--data DIR] [--port 7840]      # dev helper: / = page, /data/ = the page inputs only (DATA_FILES; events/ and otel/ are never served), POST /console (--log FILE to write elsewhere)
python3 05-dashboards/standalone/serve.py --data 02-measure/tests/fixtures/readouts   # fixture
```

Data dir default: `--data` > `$OTM_DATA_DIR` > `~/.local/share/opentokenmini`. Binds 127.0.0.1. Any static server works too, e.g. from the repo root `python3 -m http.server 7841` and open `/05-dashboards/standalone/?src=../../02-measure/tests/fixtures/readouts/`. Opening the file directly (`file://`) cannot fetch data.

Telemetry: only under `serve.py` (it sends header `X-OTM-Dev`), the page appends console errors/warnings, uncaught errors, rejections, long tasks (> `LONG_TASK_MS`) and slow frames (> `SLOW_FRAME_MS`) to `/tmp/otm-dashboard-console.jsonl` (`LOG` in serve.py), plus one `load` event listing the files found, their sizes, render times (ms) and time to loaded. Read that file instead of opening devtools. Missing optional files appear as 404s in the browser network log, not in this log.

Tests: `05-dashboards/tests/test_dashboard.py` (serve.py endpoints; page script run against a stub DOM by `05-dashboards/tests/fixtures/dashboard/smoke.js` when `node` is installed, on the fixture, on an empty dir, with the delivery fixtures in `02-measure/tests/fixtures/readouts/delivery/` copied next to it, and with skipped readout sections).

## Reconfigure

No config keys: the page reads files only. Point it elsewhere with `?src=` (any URL prefix the browser can fetch, same origin unless CORS allows). Tunables are constants at the top of the script: `LIST_MAX` (rows before "view more"), `CHART_H`, `LONG_TASK_MS`, `SLOW_FRAME_MS`, `STALE_H`, `FILES` (file names tried per input, first found wins), colors. UI strings (labels at most 3 words) are in the `S` table.

Decisions are attached by `subject`: outliers match `<metric>:<group>:<session_id>`, then `<metric>:<group>`, then `<session_id>`; recommendations match `<id>` or `recommendation:<id>`. Latest matching decision wins. All decisions also appear in the Decisions panel (to review card).

Example, show 10 rows per list and read a shared folder: set `const LIST_MAX = 10;` and open `/?src=/shared/otm/`.

## Adapt, trade-offs, decisions for the human

- Adapt: point `?src=` at wherever the outputs live, or rebuild the views in the team's existing tool (`../AGENTS.md`).
- Trade-offs: one static file, no build, no dependencies; it computes no numbers, so it never disagrees with the analysis but cannot show anything the analysis did not write.
- Decisions for the human: what the redesigned page should show first, and for whom (developer, team lead, budget owner).
