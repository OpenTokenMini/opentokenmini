# analyze: specs

Code: `analyze/analyze.py` (M-*), `analyze/outliers.py` (O-*). Constants named here are at the top of those files. Test: `03-analyze/tests/test_analyze.py`, fixture `03-analyze/tests/fixtures/analyze/events/` (worked examples below use it, `--now 2026-10-05T00:00:00Z`).

## M-filter
`--harness ID` keeps events of that harness. `--days N` keeps events with `now - N days <= ts <= now`. Filters apply before dedup. Events are sorted by (ts, harness, session_id, source, request_id, input order); every sum follows this order, so output is byte-identical for the same input and `--now`.
Example: `--days 2.5` keeps events from 2026-10-02T12:00Z → 3 sessions (s-cc-11 at 09:00 is cut, s-cx-2/3, s-oc-1 stay).

## M-dedup: otel vs transcript
`prefer` = config `analyze.prefer_source` (default `otel`); `other` = the other source. In order:
1. Same source, same `(harness, request_id)`, request_id non-null: keep the first, drop the rest.
2. An `other` event whose `(harness, request_id)` appears in `prefer`: dropped.
3. For each `(harness, session_id, kind)` with `prefer` events, window = [first, last] `prefer` ts ± `DEDUP_SLACK_S`. An `other` event of that key inside the window is dropped when its request_id is null, or when the `prefer` events of that key carry no request ids (ids cannot be compared).
Kept otherwise: `other` events outside the window (partial otel coverage), `other` sessions with no `prefer` events, `other` events with an id unknown to `prefer`. Per-kind windows keep transcript prompts when otel logs only api calls. Drops are counted in `coverage.<harness>.duplicates_dropped`.
Example: claude-code drops 31 = 10 transcript prompts (rule 3) + 20 transcript calls (rule 2) + 1 null-id transcript call in s-cc-01 (rule 3); the repeated otel `r2b` is rule 1. s-cc-11 is transcript only and kept.
M-dedup-ttl: on a rule-2 drop, if only the dropped event has `cache_write_5m/1h`, the kept event takes its `tokens`, `cost`, `cost_basis` and loses `cache_split` (claude: OTel identity and duration, transcript TTL-priced cost). OTel-only calls keep the N-claude-ttl upper bound.

## M-session
Group kept events by `(harness, session_id)`. `start`/`end` = min/max ts. `active_minutes` = Σ over consecutive events of min(gap, `IDLE_CAP_S`) / 60, rounded to 4 places (one event → 0). `calls` = api_call count; `turns` = user_prompt count; `errors` = api_calls with non-null error; `retries` = Σ retries; `tokens`, `cost` = Σ over api_calls; `subagent_cost` = Σ cost.total of api_calls with `subagent:true` (child sessions stay separate sessions, never added to the parent); `cost_basis` = C-basis-worst; `models` = {model or "unknown": cost}; `tools` = {name: occurrences in api_call.tools}; `project`, `repo`, `user` = first non-null in ts order; `sources` = sorted sources present.
Example: s-cc-01 events at +0 s, +10 s, +70 s → active_minutes 1.1667, cost 0.21, basis reported.

## M-mcp
A tool named `mcp__<server>__<tool>` is an MCP use of `<server>`. Uses are counted from api_call.tools; a tool_decision counts only if its tool is in no api_call.tools of the session. Errors = uses on events with non-null `error` (the event schema has no per-tool result, so an API error on a call that used the tool counts against it). `by.mcp[].error_rate` = errors / calls, null at 0 calls.
Example: s-cc-03 call b (error "500") used `mcp__git__log` → git calls 1, errors 1, rate 1.0.

## M-totals
`totals.cost`, `tokens`, `calls`, `turns`, `subagent_cost` = Σ sessions; `sessions` = count; `projects` = distinct project labels. Therefore totals = Σ sessions = Σ deduped api_call events.
Example: 4.55 USD, 28 calls, 15 sessions, 15 turns, 3 projects, subagent 0.14.

## M-coverage
Per harness in `readers.enabled` (or `--harness`) plus any seen: `events` (kept), `sessions`, `first_ts`, `last_ts`, `sources`, `cost_basis_share` = api_calls per basis / api_calls, `unpriced_calls` = api_calls with basis `unknown` (cost 0, never guessed), `duplicates_dropped`; `reason: "no events"` when empty.
Example: opencode unpriced_calls 1; antigravity reason "no events".

## M-by-day, M-by-dim, M-tool-cost
`by.day`: Σ api_call cost.total per UTC day of the event ts, per harness. `by.harness|model|project`: rows {name, cost, sessions, calls}, cost desc then name; model null → "unknown". `by.tool` (M-tool-cost): each api_call's cost.total split equally among its `tools`; `calls` = occurrences; calls without tools are not attributed, so Σ by.tool ≤ total.
Example: Bash 4.36 USD over 20 uses.

## Group metrics
Computed for group `null` (all) and per harness; `n` = sessions in the group; `session_ids` = top `TOP_SESSIONS` sessions by cost (ties by id). Any ratio with a zero denominator is `null`. Sums over the group's sessions/events.
- `M-spend` = Σ cost.total (USD).
- `M-cost-share-input`, `M-cost-share-output`, `M-cost-share-cache-read`, `M-cost-share-cache-write` = cost.<type> / cost.total. Reasoning is inside output (C-list). Example: 0.25, 0.5, 0.25, 0.
- `M-cache-hit-rate` = cache_read / (input + cache_read + cache_write) tokens (tokens are disjoint, C-tokens). Example: 1000/1100 = 0.9091.
- `M-cost-per-call` = spend / calls. Example: 4.55/28 = 0.1625.
- `M-calls-per-turn` = calls / turns. Example: 28/15.
- `M-subagent-share` = Σ subagent_cost / spend. Example: 0.14/4.55.
- `M-top-model-share` = max model cost / spend.
- `M-session-cost-median` = median session cost.total over sessions with calls ≥ 1. Example: 0.24.
- `M-session-cost-p90` = nearest rank: sorted costs [ceil(`P90` · n) − 1]. Example: 0.29.
- `M-error-rate` = errors / calls. `M-retries-per-call` = retries / calls. Example: 1/28 each.
- `M-mcp-error-rate` = Σ MCP errors / Σ MCP uses (M-mcp). Example: 1.0; codex null.
- `M-approval-rate` = tool_decision with decision accept / tool_decisions. Example: codex 0.5.
- `M-human-decision-share` = tool_decisions with decision_source in `HUMAN_SOURCES` / tool_decisions. Example: codex 0.5.

## Session metrics (outlier inputs)
- `M-session-cost` = session cost.total; sessions with 0 calls left out.
- `M-session-cost-per-call`, `M-session-calls-per-turn` (null at 0 turns), `M-session-cache-hit-rate`: same formulas on one session; left out when calls < `MIN_CALLS_RATIO` (too noisy).

## O-robust-z
Per session metric, per baseline group (O-model-group), over the sessions with a value: med = median(x); MAD = median(|x − med|); scale = `MAD_SCALE`·MAD, or `MEANAD_SCALE`·mean(|x − med|) when MAD = 0; z = (x − med)/scale (scale 0 → no outliers). Outlier when |z| ≥ `Z_THRESHOLD` (3.5), two-sided, score rounded to 4 places, baseline = med, n = group size. `flagged` = n ≥ `MIN_SAMPLE` (8); below it the candidate is reported with `flagged:false` (decide should only explain flagged ones). Sorted by |score| desc.
O-model-group: sessions are grouped by (harness, main model), main model = the model with the most cost in the session (ties by name; none → "unknown"); `group` = `<harness>/<model>`. A (harness, model) group with fewer than `MIN_GROUP` (20) sessions holding a value for that metric is not scored alone: its sessions are scored against the whole-harness baseline (all sessions of that harness with a value), and their outliers carry `group` = `<harness>` and that baseline's n. Per (harness, metric) the outliers are sorted by |score| desc. Why: grouped by harness only, the claude-code baseline is a cheap haiku session, so most flags just meant "opus session" or "haiku session". Real 30-day data (1185 sessions, `--now 2026-10-18T21:00Z`): 273 → 122 flagged; cost-per-call 182 → 29.
O-log-scale: metrics with `"scale": "log"` in `metrics.json` (`M-session-cost`, `M-session-cost-per-call`: right-skewed USD) take x = log10(value); values ≤ 0 are left out; `baseline` = 10^med (value units), `value` stays in value units, `score` is the log-space z. Why: on real 30-day data (1075 claude-code sessions) linear z flagged 443 session costs (41%), log z flags 14.

O-spread-floor: metrics with `"spread_floor": true` in `metrics.json` (`M-session-calls-per-turn`, linear scale) use scale = max(scale, `MIN_REL_SPREAD`·|med|), `MIN_REL_SPREAD` = 0.5, so only values beyond ~2.75x the median (or under ~-0.75x, i.e. never for counts) are outliers. Why: calls per turn is a small discrete ratio; on real 30-day data the haiku group (n 604, median 4.5, MAD 1) flagged 56 sessions at 10-14 calls/turn, normal for one-prompt subagent sessions. Not used for ratios in [0, 1] (cache hit rate), where a median-relative floor would hide real drops.
Example: claude-code session costs 0.21..0.29, 0.24, 2.00 (n 11) → log scale: med log10(0.25), z(s-cc-10) = 16.821, flagged (linear would be 1.75/(1.4826·0.02) = 59.0179). Log of `[1,2,3,1,2,3,1,2,3,30, 0]` → 0 left out (n 10), only 30 flagged. Values [1, 1.1, 0.9, 50] → "d" reported unflagged.

## M-recommendation-evidence
Per harness with sessions, each candidate in `metrics.json` `recommendations` with its evidence metric values for that harness (skipped when all are null); `id` = `<candidate id>/<harness>`, `p_yes` and `verdict` null until decide fills them. Analyze judges nothing.
Example: 11 rows (5 claude-code, 4 codex: no MCP, 2 opencode: shares null, cache hit rate and cost per call present).
