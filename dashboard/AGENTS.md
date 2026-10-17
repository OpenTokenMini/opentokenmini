# dashboard

Shows metrics, outliers and recommendations from `../analyze/` to people. Its agent-facing twin is `../mcp-server/`. Metrics are configurable per deployment.

- Input: `../analyze/output.md`; raw records from `../measure/` until analyze exists.
- Output: a web page. Human-facing: all text internationalized.
- Data it touches: read-only.

Today a minimal version is embedded in `../measure/collector.py` (`GET /`): raw records and a histogram of `api_request` fields.

## Files

- `metrics.md` metric catalog; each deployment picks and edits its own.

## To do

- mockups, then the screenshot used by every README and `../docs/demo/`
- org-wide view that says what to change, not only what happened
- same views as Datadog or Grafana dashboards when data lives there
