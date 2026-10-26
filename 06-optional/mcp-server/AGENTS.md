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

## live.py (otm-live): live sessions for an orchestrator

Separate stdio MCP server over the agent sessions running on this machine (design: `orchestrator-interface.md`). Reads `~/.claude/sessions/<pid>.json` (live registry), `~/.claude/projects/*/<sid>.jsonl` and `<sid>/subagents/agent-*.jsonl` + `.meta.json` (incremental, last `MAX_SCAN_BYTES` per file), and `/run/user/1000/bgjobs/quota_cache.json`. Cost = transcript usage x `02-measure/schemas/prices.json`. Writes only `<data dir>/live/` (cursors, declarations, pending delegations, `calls.jsonl`) and `<data dir>/delegations.jsonl`. No network.

```
claude mcp add -s user otm-live -- python3 /abs/path/06-optional/mcp-server/live.py
python3 06-optional/mcp-server/live.py --call overview --args '{"caller":"x","full":true}'   # CLI, same JSON
```

The live dashboard serves the same tools at `GET /api/<tool>?k=v` (`05-dashboards/live/serve.py`).

Call log: every tool call through `call_tool` (MCP `via: "mcp"`, `/api` `via: "api"`; CLI `--call` is not logged) appends `{ts, tool, args (≤ CALLS_ARGS_CHARS), ms, chars (result text length), ok, via, err (if not ok)}` to `<data dir>/live/calls.jsonl`. Past `CALLS_MAX_LINES` lines it is cut to the newest half. Logging failures are swallowed.

| tool | arguments | returns |
|---|---|---|
| `overview` | full, window_h, caller | per session: name, state, cost, ctx_k, touching, goal (+goal_src), `subagents` lines `desc \| model \| ctx \| cost \| min \| last tool \| status` (newest `SUB_LINES`); quota; inferred overlaps and low-return subagents; last `LEDGER_LINES` of the delegation ledger. Without full, only sessions changed since this caller's last call (cursor per caller) |
| `session` | id_or_name, limit | goal, state, recent turns, files touched (`SESSION_FILES`), subagents with cost and returned size (`tok` only in `node`); limit caps all three lists |
| `agents` | session (default: caller's), window_h, limit, all, since | delegation tree (`agents.v1`): `{session:{name,sid,state}, totals:{cost,orch_cost,workers_cost,workers,running,partial,next,to_merge,median_ctx_k}, agents:[{id,parent,desc,model,state,cost,ctx_k,peak_ctx_k,turns,tool_calls,started,last,duration_s}], omitted}`; worker `last`/`duration_s` use the last in-transcript work event (assistant line, tool result or prompt), so task notifications appended to a finished worker's file later don't stretch them (`[SYSTEM NOTIFICATION` is also not a prompt); agents[0] = main (parent null), workers by start. Workers (not main) also carry `result` (string or null: first `AGENT_RESULT_CHARS` (200) of the result the parent received, else the last assistant text, markdown marks (`**`, backticks, leading `- `/`#`/`1.`) dropped, whitespace collapsed; null while working or if empty), `outcome` (`ok`|`partial`|`failed`, null while working): from the first `OUTCOME_TEXT_CHARS` of the final text: context-limit/soft-limit/not-committed/nothing-committed/didn't-finish/isn't-finished-or-started phrases -> partial; a commit hash next to "commit" -> ok even with failure words; only ok words (committed, commit + hash, tests pass) -> ok (partial if the prompt mentions commit but no hash); only failure words -> failed; otherwise local d1 (`D1_URL`, choice, `D1_TIMEOUT_S`; below `D1_MIN_P` or any failure -> fallback, and a failure disables d1 for the process) else ok/partial by the commit rule; cached per agent id + text, and `wt` (null or `{path,branch,ahead,dirty,merged}`): the linked git worktree of the worker: its `.meta.json` `worktreePath` (Claude Code `isolation: "worktree"`, `<repo>/.claude/worktrees/agent-<id>`), else the first absolute path in the worker's first prompt that lies in one, else the transcript's `cwd`; a linked worktree is (a dir with a `.git` *file*; a `.git` dir = main checkout, skipped). `ahead` = `rev-list --count <main>..HEAD`, main = the branch (else HEAD) of the first entry of `git worktree list`; `dirty` = lines of `git status --porcelain`; branch = `HEAD` if detached. `merged` = ahead 0 (tip is an ancestor of main) and the tip differs from the branch's oldest reflog entry (where it was created), so a fresh untouched branch is not merged; fast-forward and --no-ff merges both count; false without a reflog. A worktree path that no longer exists -> `wt: null` (removed after merge; no branch lookup). Git results cached per path `WT_CACHE_S` (10 s); for finished workers reused up to `WT_DONE_CACHE_S` while the mtimes of the worktree's HEAD/index/logs and the main repo's logs/HEAD, packed-refs, refs/heads are unchanged (git subprocesses were ~85% of a call), each git call `GIT_TIMEOUT_S` (2 s), any failure -> null. Finished workers may carry `handoff` (omitted if none): the first existing `.../handoffs/*.md` path named anywhere in the final text, else `HANDOFF_DIR/<full agent id>.md` if it exists. Workers may carry `next` (omitted if none): `merge` (ahead > 0, not dirty, outcome ok), `inspect` (ahead > 0 but dirty or not ok; partial without handoff; failed), `resume` (partial with handoff); none while working, if `wt.merged`, or if a later-started worker reuses its worktree path or names its handoff in its first prompt (already resumed/redone). `totals.next` = nonzero counts per hint. `totals.to_merge` = workers with `wt.ahead > 0` and not merged; `totals.partial` = workers with outcome partial. Default: all running workers plus the `AGENTS_RECENT_DONE` (5) most recently finished, and `omitted` counts the rest (totals always cover every worker). `all: true` lists every worker (`omitted` 0); the dashboard uses this. Then the newest `AGENTS_ROWS` are kept (`truncated.agents` = full count); parent from `.meta.json` parentAgentId for nested; turns = model calls; window_h keeps workers written in the window. Transcript-only: telemetry has no subagent split. `since` (string) switches to the heartbeat view instead: `{cursor, basis, summary, changed:[{id,desc,state[,outcome,next,branch,handoff,was]}], unchanged}`. Pass back `cursor` (epoch seconds) next beat; changed = workers (all, untrimmed) whose `[state, outcome, next]` differ from the snapshot saved under that cursor (`basis: cursor`; `<data dir>/live/agents_cursors.json`, last `AGENTS_CURSORS_KEEP` per session, so several callers can poll); `was` = previous state. An ISO time picks the newest snapshot at/before it; with none (or an unknown cursor) -> workers working or active in the last minute before it (`basis: activity`). `""` = first beat: running + workers with a next (`basis: actionable`). `branch` only with next, `handoff` only with next resume. `summary` = `N running, <count> <next>..., quota 5h 19% 7d 38%` (`<win> reset` once passed, `stale Nm` past `QUOTA_STALE_MIN`, `quota ?` if no cache), so one call answers a heartbeat. Real (session with 46 workers): agents 4.6k + overview full 2.9k chars per beat -> 460 first beat, ~120 with nothing changed; warm ~85 ms |
| `node` | session, node (`t<N>` or subagent id prefix) | model, tokens, duration, tools, returned size, result excerpt |
| `who_touches` | path or port, window_h | sessions/subagents that edited/read the path or mention/listen on the port |
| `declare` | goal, claims, caller | stores goal and claimed paths/`port:N`; returns overlaps |
| `method` | id | what an inferred metric id computes |
| `record` | phase (`start`\|`end`), item, agent, desc, topology, tokens, commit, tests_pass, accepted | start stores quota_before (bgjobs `out` %) per item; end appends `{ts, agent, desc, item, topology, quota_before, quota_after, tokens, commit, tests_pass, accepted}` to `delegations.jsonl` |
| `mcp_status` | hours (default 24), verbose | default compact: `tools` only those with calls, `unused:[names]` for the rest, `recent` newest `STATUS_RECENT_COMPACT` (5) without `args`; `verbose: true` (dashboard) returns the full shape: `{server:{name,pid,started,version (git short sha or null),log,stale (live.py on disk newer than this process)}, window_h, calls, errors, tools:[{name,calls,errors,p50_ms,p95_ms,avg_chars,max_chars,last}] (every tool, by calls desc), orchestrators:[{sid,name,calls,tools:{tool:n},last}] (sessions whose main/subagent transcripts have `mcp__otm-live__*` tool_use in the window, newest `STATUS_ORCH`), recent:[{ts,tool,via,ms,chars,ok,args}] (newest `STATUS_RECENT`)}`; pid/started are the answering process (MCP and `/api` differ). When stale, top-level `stale` holds one line (`live.py changed at HH:MM after this server started at HH:MM; restart the MCP to get new tools/args`), also appended to unknown-argument errors. Branch = the worktree's checked-out branch: a worker that runs `checkout -b` inside the harness worktree is reported on its new branch; commits on a branch it then leaves are not seen |

Constants at the top of `live.py` (windows, caps, thresholds). Results trimmed to `MAX_RESPONSE_TOKENS` like `server.py`. Subagent ids are shown as `ID_CHARS` prefixes; `agg` is a method id (`method agg.v1`). Real data (~chars/4): overview full 784 -> 708 tok (8 sessions), session 1663 -> 1295 (23 subagents), agents ~2.8k for 21 workers (all, with result/wt; first call ~1.3 s, cached 0.07 s; with git cache aged past WT_CACHE_S 0.88 s before the signature cache, 0.17 s after). mcp_status ~3.8k chars verbose, ~1.4k compact. Tests: `06-optional/tests/test_live.py` (synthetic transcripts in temp dirs). Not implemented: the `efficiency` block of the design.

## Pending

- Breakdowns per subagent type and per session (today `usage_breakdown` by `subagent` is per harness).
- Recommendations ranked by expected savings.

## Adapt, trade-offs, decisions for the human

- Adapt: `mcp.source` to where outputs live; `PRIVATE_KEYS` to hide more fields; `MAX_RESPONSE_TOKENS` and page sizes to the orchestrator's context budget.
- Trade-offs: read-only and pre-computed, so answers are cheap and consistent with the dashboard, but only as fresh as the last pipeline run. Hard response caps keep context small and may truncate lists (`truncated`, `next_offset`).
- Decisions for the human: which agents may register it; whether per-session data should be exposed to agents at all.
