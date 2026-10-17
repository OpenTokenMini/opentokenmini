# dashboards

One or more views for people: a standalone page, or dashboards inside the monitoring the user already runs (Datadog, Grafana). Each shows metrics, outliers and recommendations from `../03-analyze/` to people. Its agent-facing twin is `../06-optional/mcp-server/`. Metrics are configurable per deployment.

- Input: `../03-analyze/output.md`; raw records from `../02-measure/` until analyze exists.
- Output: a web page. Human-facing: all text internationalized.
- Data it touches: read-only.

Today a minimal version is embedded in `../02-measure/collector.py` (`GET /`): raw records and a histogram of `api_request` fields.

## Files

- `metrics.md` metric catalog; each deployment picks and edits its own.

## To do

- mockups, then the screenshot used by every README and `../00-docs/demo/`
- org-wide view that says what to change, not only what happened
- same views as Datadog or Grafana dashboards when data lives there
