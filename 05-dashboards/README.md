# Dashboards

`reference/` is the reference dashboard: the layout every view should follow. It runs on sample data.

![Reference dashboard](reference/screenshot.png)

Open `reference/index.html` in a browser, or run `python3 reference/serve.py` (http://127.0.0.1:7844/, logs browser errors to `/tmp/otm-dashboards-console.jsonl`).

- Individual / Team / Org switch the level: sessions, people or teams.
- Cost and volume are measured sums over the window; effectiveness is inferred (method still open). Hover any number to see how it was computed.
- Histogram: one bar per day. Above the axis, token volume colored by effectiveness (red to green); below it, cost.
- Click a card to inspect it; Fix opens the same inspector with the cursor in the fix box.

`live/` is the dashboard on your own data: `python3 live/serve.py` (http://127.0.0.1:7845/). It reads the last 24 h from the collector's file sink and session titles from local Claude Code transcripts; if the local decision model (:6975) is up it classifies each prompt into Runtime / UI / Infra / Docs. The Live tab (`#live`) lists the sessions running on this machine and the quota; open one to see its delegation view: the main agent and its subagents on a time axis, with workers over 150k context or idle for 10 min while running flagged. It reads `/api/<tool>`, the same functions as the `otm-live` MCP server (`../06-optional/mcp-server/live.py`). `?dev#live` falls back to `live/agents-fixture.json` when `/api/agents` is missing.

`standalone/` is a draft page on the batch pipeline outputs (`03-analyze/pipeline.py`, including `readout.json`): `python3 standalone/serve.py` (http://127.0.0.1:7840/). It shows the data age and renders any `readout.json` section without its own panel as a small card. Not yet on the reference layout.
