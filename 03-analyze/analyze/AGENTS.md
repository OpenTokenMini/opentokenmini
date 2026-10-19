# analyze

Turns events into sessions and one analysis: dedups otel vs transcript, builds sessions, computes the metric catalog (`metrics.json`), flags outlier sessions (robust z) and lists recommendation candidates with evidence for decide. Specs: `METHOD.md`.

Input: `<data>/events/*.jsonl` (event schema). Output: `<data>/sessions.jsonl`, `<data>/analysis.json` (rewritten each run). Data touched: only those. No network, no jev.

```
python3 03-analyze/analyze/analyze.py                                   # data dir from OTM_DATA_DIR / config / default
python3 03-analyze/analyze/analyze.py EVENTS_DIR --out DIR --days 30 --harness codex --now 2026-10-05T00:00:00Z
```
`--now` fixes "now" for `--days` and `generated`, for reproducible runs. Summary goes to stderr. Check outputs with `python3 02-measure/schemas/check.py <file>`.

## Reconfigure

Config key `analyze`: `source` (default `files`), `sink` (default `files`), `prefer_source` (`otel` or `transcript`, M-dedup). Connectors live in `connectors.py`:

- sources `SOURCES`: `files` (events dir), `stdin` (event JSONL on stdin). Signature `load_events(cfg) -> Iterable[event]`.
- sinks `SINKS`: `files` (sessions.jsonl + analysis.json in the out dir), `stdout` (analysis JSON only). Signature `write_outputs(sessions, analysis, cfg) -> None`.

Paths resolved by the CLI are in `cfg["analyze"]["_events_dir"]` and `cfg["analyze"]["_out_dir"]`.

Worked example, send the analysis to a warehouse loader instead of files:
```python
def warehouse_sink(sessions, analysis, cfg):
    import subprocess, json
    subprocess.run(["load-analysis"], input=json.dumps(analysis), text=True, check=True)
SINKS["warehouse"] = warehouse_sink
```
then `01-deploy/config.json`: `{"analyze": {"sink": "warehouse"}}`.

Add a metric: add `{id, scope, unit, name, definition}` to `metrics.json`, its value in `group_values` (or `session_values` for outlier inputs) in `analyze.py`, and an `M-` spec with a worked example in `METHOD.md` (the test fails on catalog ids missing there). Thresholds are constants at the top of `analyze.py` and `outliers.py`.

## Adapt, trade-offs, decisions for the human

- Adapt: metrics in `metrics.json`, thresholds at the top of `analyze.py` / `outliers.py`, source and sink connectors to the team's storage.
- Trade-offs: robust z-scores flag unusual sessions, not wasteful ones; small samples give unstable outliers. Recommendation candidates come with evidence but no verdict; judging them is left to decide or a person.
- Decisions for the human: which metrics matter for this team; which recommendations to apply (`03-analyze/recommendations.md`); `prefer_source` when OTel and transcripts disagree.
