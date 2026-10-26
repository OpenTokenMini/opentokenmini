# context: specs

Constants at the top of `context.py`: `DAYS=30`, `CHARS_PER_TOKEN=4`, `IMAGE_TOKENS=1500`, `THRESHOLDS=(150k, 250k)`, `CURVE_TURNS=(1,10,25,50,100,200)`, `CURVE_POINTS=20`, `TOP_TOOLS=5`, `MAX_READOUT_BYTES=400`.

## X-scan: what is read
Every `*.jsonl` under the root modified at or after since; lines with `timestamp >= since` (R-window). One file is one context thread; files under `subagents/` belong to their parent `sessionId`. API calls dedup by request id, last usage wins (R-claude-dedup), `<synthetic>` skipped. `tool_use` blocks dedup by id.

## X-ctx: context per turn
ctx = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of one call. The curve is the main thread only (not subagent files, not sidechain lines), in log order; `peak_ctx` is its max. `curve` in detail is downsampled to `CURVE_POINTS`; `curve_median` is the median ctx at each of `CURVE_TURNS` over sessions that reached it.

## X-peak
`over_150k` / `over_250k`: sessions whose `peak_ctx` reaches the threshold.

## X-compact
Each `compact_boundary` line is one compaction; before/after = `compactMetadata.preTokens` / `postTokens`, else the ctx of the calls just before and after it.

## X-cache
Shares of ctx tokens over all calls (main and subagents): cache read, cache write, uncached input. Cache write cost = C-cache-ttl list price (5m/1h split when logged), via `schemas/cost.py`.

## X-reread
In one thread, a `Read` with the same (file_path, offset, limit) as an earlier one, with no `Edit`/`Write`/`MultiEdit`/`NotebookEdit` to that file in between, is a re-read; its result tokens are wasted. Pitfall: a file changed outside the agent (git checkout, a script) is legitimately re-read.

## X-size, X-tools
Result tokens = ceil(chars / `CHARS_PER_TOKEN`), `IMAGE_TOKENS` per image (as M-size). Top `TOP_TOOLS` tool names by summed result tokens.

## X-readout
`readout`: sessions, peak_p50, over_150k, over_250k, compactions, cache_read_share, cache_write_usd, reread_tok, up to 3 `findings` (facts), `detail` = `context.json`. Findings are dropped from the end until the compact JSON is under `MAX_READOUT_BYTES`.

## X-ex: worked example (../tests/test_context.py)
since 2026-10-01. s1 main: a Sep 30 call (dropped); r1 (logged twice) ctx 1010, Read /a 100 tok; r2 1205, Read /a again = re-read 100 tok; r3 1201 Edit /a; r4 1251 Read /a (not a re-read: edited); compaction 1300 -> 300; r5 300, Bash 1000 tok. s1 subagent: cache write 160000, Read /a (own thread, not a re-read). s2: one call, ctx 260000. Peaks: s1 1251 (subagent excluded), s2 260000 -> over_150k 1, over_250k 1. Re-reads 1 / 100 tok. Tools: Bash 1000, Read 203, Edit 1.
