# mcp

Read-only MCP server for agents: answers questions about spend, metrics, outliers, sessions, commit impact and decisions from the files the other stages wrote. Computes no new numbers. Never returns raw events, prompts or repo paths (`repo` is dropped from every record).

Input (data dir, via the `files` source): `analysis.decided.json` if present, else `analysis.json`; `sessions.jsonl`; `impact_summary.json`; `decisions.jsonl`. A missing file only fails the tools that need it. Output: JSON-RPC responses on stdout. Writes nothing.

## Run

```
python3 06-optional/mcp-server/server.py [--config PATH]     # stdio, one JSON message per line
```

Register it in a harness yourself (not done by this repo), e.g. Claude Code `claude mcp add opentokenmini -- python3 /abs/path/06-optional/mcp-server/server.py`, or in any MCP client config: `{"command": "python3", "args": ["/abs/path/06-optional/mcp-server/server.py"], "env": {"OTM_DATA_DIR": "..."}}`.

Smoke test:
```
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"summary","arguments":{}}}' | python3 06-optional/mcp-server/server.py
```

## Tools

| tool | arguments | returns |
|---|---|---|
| `summary` | days or since (YYYY-MM-DD) | generated, period, filters, totals, by_harness, by_model (+cost_per_call, cost_per_session), by_project (first `SUMMARY_ROWS` each), truncated {list: full length}; with days/since also `window` {since, days, cost, by_harness} from `by.day` (totals and by_* stay full period) |
| `outliers` | metric, group, detail, offset, limit | page of `analysis.outliers`; compact by default (decision -> {choice, p}, no session_ids), `detail: true` for full |
| `metric` | id, group, offset, limit | page of `analysis.metrics` |
| `session` | session_id, or harness, project, offset, limit | one session record, or page of {session_id, harness, project, start, calls, cost} by cost desc |
| `impact` | by (`repo`\|`harness`), offset, limit | impact summary totals + page of rows |
| `decisions` | point, subject, detail, offset, limit | page of decisions, newest first; compact {ts, point, subject, choice, p} unless `detail: true` |
| `recommendations` | harness, verdict (`suggest`\|`skip`\|`unsure`), detail, offset, limit | page of `analysis.recommendations` {id, candidate, harness, verdict, p_yes, decided}; joined to the latest `recommendation` decision by subject = id `<rec id>/<harness>`; `detail: true` adds evidence |
| `usage_breakdown` | by (`tool`\|`mcp`\|`subagent`, default tool), days (subagent only) | top 10 rows: tool {name, cost, calls, share of total cost}; mcp {server, calls, errors, error_rate}; subagent {harness, sessions, cost, subagent_cost, subagent_share} + overall share, from sessions.jsonl (days = sessions started in the last N days). by.tool has no error rate and by.mcp no cost in analysis.json |
| `coverage` | harness | `analysis.coverage` (one harness or all) |

Pages are `{items, total, offset, next_offset}`; `next_offset` is null on the last page. `limit` defaults to `DEFAULT_LIMIT` (10) and is capped at `MAX_ITEMS` (50). Every result is trimmed to `MAX_RESPONSE_TOKENS` (2000, ~chars/4): pages drop trailing items and `next_offset` points at the first dropped one; other results shorten their longest lists and record it in `truncated`. Errors: missing file or unknown id → result with `isError: true` and a one-line text; unknown tool, non-object params/arguments, unknown argument, wrong type or value below minimum → -32602; no `jsonrpc: "2.0"` or no method → -32600; unknown method → -32601; unexpected failure → -32603 for that request only (the server keeps serving). `initialize` echoes the client's `protocolVersion` if it is in `PROTOCOL_VERSIONS`, else the newest listed.

## Reconfigure

Config key `mcp.source` (default `files`) picks a function from `SOURCES` at the top of `server.py`. Signature: `load(name: str, cfg) -> dict | list | None`, where `name` is one of the file names above, `.jsonl` returns a list of records, and `None` means absent.

Example: serve outputs from a shared HTTP host instead of the local data dir.

```python
def http_source(name, cfg):
    import urllib.request, urllib.error
    try:
        body = urllib.request.urlopen(f"https://reports.example/otm/{name}").read().decode()
    except urllib.error.HTTPError:
        return None
    return [json.loads(l) for l in body.splitlines() if l.strip()] if name.endswith(".jsonl") else json.loads(body)

SOURCES = {"files": files_source, "http": http_source}
```

then `01-deploy/config.json`: `{"mcp": {"source": "http"}}`. To hide more fields, add keys to `PRIVATE_KEYS`. Tests: `06-optional/tests/test_mcp.py` (fixtures in `02-measure/tests/fixtures/readouts/`, sessions from `02-measure/tests/fixtures/schemas/`).

## Pending

- Breakdowns per subagent type and per session (today `usage_breakdown` by `subagent` is per harness).
- Recommendations ranked by expected savings.

## Adapt, trade-offs, decisions for the human

- Adapt: `mcp.source` to where outputs live; `PRIVATE_KEYS` to hide more fields; `MAX_RESPONSE_TOKENS` and page sizes to the orchestrator's context budget.
- Trade-offs: read-only and pre-computed, so answers are cheap and consistent with the dashboard, but only as fresh as the last pipeline run. Hard response caps keep context small and may truncate lists (`truncated`, `next_offset`).
- Decisions for the human: which agents may register it; whether per-session data should be exposed to agents at all.
