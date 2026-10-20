# dashboards

One or more views for people: a standalone page, or dashboards inside the monitoring the user already runs (Datadog, Grafana). Each shows metrics, outliers and recommendations from `../03-analyze/` to people. Its agent-facing twin is `../06-optional/mcp-server/`. Metrics are configurable per deployment.

- Input: outputs of `../03-analyze/`, `../04-auto-analysis/impact/` and `../06-optional/decide/` in the data dir (contract: `../03-analyze/output.md`).
- Output: a web page. Human-facing: all text internationalized.
- Data it touches: read-only.

The collector no longer embeds a dashboard. `reference/` is the agreed layout (sample data); `standalone/` is the page on real data, to be rebuilt on that layout.

## Files

- `reference/` reference layout on sample data, its screenshot and dev server (`serve.py`, port 7844).
- `live/` dashboard on real data (collector file sink + local transcripts), dev server `serve.py`, port 7845.
- `standalone/` earlier static page and dev server (`serve.py`, port 7840).
- `tests/` unit tests for `standalone/`.
- `metrics.md` metric catalog; each deployment picks and edits its own.

## To do

- mockups, then the screenshot used by every README and `../00-docs/demo/`
- org-wide view that says what to change, not only what happened
- same views as Datadog or Grafana dashboards when data lives there
