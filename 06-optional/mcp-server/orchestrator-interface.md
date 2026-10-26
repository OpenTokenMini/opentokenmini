# Orchestrator interface (implemented in live.py)

Proposed shape of what an orchestrating agent (or a subagent avoiding collisions) reads about live sessions. Transport-agnostic: MCP tools, a CLI or an HTTP endpoint return the same JSON. Compact form of the otm-panel view; same data contract, same method ids. Example values below are illustrative, not measured.

## Rules

- Three levels, one call each, every result under `MAX_RESPONSE_TOKENS`: `overview` → `session` → `node`.
- Every result separates layers: `measured` (raw, aggregation stated once per block), `inferred` (each item carries a `method` id), `efficiency` (estimate, `method` id). Labels go in the block header, not on every value.
- `method` ids resolve with `method <id>`: one line of what it computes, inputs, window. Never inlined.
- Delta by default: the server keeps a cursor per caller session (`CLAUDE_CODE_SESSION_ID`); `overview` returns only what changed since that caller's last call. `full: true` ignores the cursor.

## Tools

| tool | arguments | returns |
|---|---|---|
| `overview` | full, window | one line per live session + `delta` since caller's last call |
| `who_touches` | path or port | sessions that edited/read/bound it, with last ts |
| `session` | name or id | goal, state, tasks, recent decisions, files touched, branches with burned vs returned |
| `node` | session, node id | one branch/turn: model, tokens, duration, tools, returned size; summarized, no prompt text |
| `method` | id | what the method computes, inputs, window |
| `declare` | goal, claims | caller publishes its one-line goal and the paths/ports it intends to touch |

## Example: overview (delta)

```json
{
  "since": "2026-05-21T14:02Z",
  "delta": [
    "otm-imple: committed 3 files (02-measure/collector.py ...)",
    "otm-panel: state working -> waiting_user",
    "otm-orque: +$2.10"
  ],
  "measured": {
    "agg": "cost = sum cost_usd per session.id, since session start; state from last transcript event",
    "sessions": [
      {"name": "otm-imple", "goal": "v003 collector port", "goal_src": "declared", "state": "working", "cost": 11.4, "touching": ["02-measure/"], "last": "14:09Z"},
      {"name": "otm-panel", "goal": "operator view", "goal_src": "declared", "state": "waiting_user", "cost": 6.2, "touching": ["05-dashboards/"], "last": "14:05Z"}
    ]
  },
  "inferred": [
    {"issue": "overlap", "a": "otm-imple", "b": "otm-panel", "on": "data contract fields", "method": "overlap.paths.v1"},
    {"issue": "low_return", "session": "otm-orque", "node": "a3", "burned_k": 90, "returned_words": 400, "method": "burn_ratio.v1"}
  ],
  "efficiency": {"note": "per-session estimate", "method": "eff.ratio.v1", "items": []}
}
```

`goal_src` is `declared` (session called `declare`) or `inferred` (derived from transcript, then it moves to the `inferred` block).

As implemented (`live.py`): the goal stays on the session line with `goal_src` (not moved to the `inferred` block); the `efficiency` block is not implemented; overview adds per-session `subagents` lines and the last delegation `ledger` lines; `record` writes the ledger; an extra `agents` tool returns one session's delegation tree (`{session, totals, agents}`, main agent plus workers, parent from `.meta.json`; see `AGENTS.md`).

## Open

- Outcome signal for `efficiency` (correction turns, tests, commit survives): undecided.
- Data source for state/touching: hooks vs transcript tail. Per-instance subagent id needs join with `subagents/*.meta.json`.
- Method id naming shared with otm-panel.
