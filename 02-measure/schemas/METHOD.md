# schemas: specs

Code: `schemas/cost.py` (C-*), `schemas/check.py` (C-sum, C-cache-ttl bound, S-*). Constants named in each spec live at the top of those files.

## C-tokens: disjoint token counts
Definition: every event carries `tokens{input, output, cache_read, cache_write, reasoning}`, ints >= 0, disjoint, so their sum is the billed token count.
- `input` = uncached input only (excludes cache reads and cache writes).
- `output` = visible output only (excludes reasoning).
- When a harness reports inclusive counts, subtract: `input = input_reported - cache_read - cache_write` (flag `input_includes_cache`), `output = output_reported - reasoning` (flag `output_includes_reasoning`).
- Edge: missing count = 0; a subtraction below 0 (inconsistent harness report) is clamped to 0.
- `user_prompt` and `tool_decision` events carry all-zero tokens and cost (enforced by S-event-kind).
Worked example: harness reports input 13000 incl. cache, cache_read 10000, cache_write 2000, output 250 incl. reasoning 50 → `{input:1000, output:200, cache_read:10000, cache_write:2000, reasoning:50}`.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_tokens (also the clamp: input 5 incl. cache_read 10 → 0).

## C-price-match: price lookup
`schemas/prices.json` maps a model substring to USD per million tokens (`PER_TOKENS`) for `input, output, cache_read, cache_write`. Lookup lowercases the model id and takes the first key (file order) that is a substring of it. More specific keys come first (`opus-5-5` before `opus`). No match or null model → no price (no default).
Seeded from the old `02-measure/from-transcripts.py` (now in `02-measure/todelete/`). Estimated rows: `gpt` and `gemini` are one family-level price for all versions seen locally, with `cache_write` 0 (not billed separately); `fable` is a list price as recorded there, not re-checked. `opus-5-5` is fitted from Claude Code OTel `cost_usd` (input 4, output 20, cache_read 0.2, cache_write_5m 5, cache_write_1h 8; flat cache_write = 5m rate); `sonnet-5-5` (2/10/0.1/2.5/4) is a guess from one sample. Rows may carry a string `basis` saying where the numbers come from; cost code ignores it.
Formula: `price = prices[first k in prices if k in lower(model)]`, else None.
Edge cases: null model → None; case-insensitive (`Claude-HAIKU-5` → `haiku-5`); dated ids match their base (`claude-opus-5-5-20260901` → `opus-5-5`, not `opus`); no match → None, cost then falls to C-cost rule 4.
Worked example: `claude-opus-5-5` → key `opus-5-5` (output 20); `Claude-Opus-4-1` → key `opus` (output 25); `mystery-1` → None.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_price_match.

## C-list: list-price cost
`cost.input = input * p.input / PER_TOKENS`, `cost.output = (output + reasoning) * p.output / PER_TOKENS`, `cost.cache_read = cache_read * p.cache_read / PER_TOKENS`, `cost.cache_write = cache_write * p.cache_write / PER_TOKENS`, `cost.total` = sum of the four. Unit USD, unrounded floats. Reasoning is billed at the output rate and has no cost field of its own.
Edge cases: zero tokens → all parts 0.0; no rounding or cap on huge counts (Python floats, ~1e-16 relative error); no price → C-list does not apply (C-cost rule 4).
Worked example: model `claude-sonnet-4` (sonnet: 3, 15, 0.3, 3.75), tokens from C-tokens → input 0.003, output 0.00375, cache_read 0.003, cache_write 0.0075, total 0.01725.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_list.

## C-allocate: reported total only
When the harness reports one USD total and no per-type split: weights = C-list parts if the model is priced and their total > 0; else token counts per type (reasoning added to output); `part = total * weight / sum(weights)`. If all weights are 0 the whole total goes to `input`. `cost.total` = the reported total exactly; parts match it within `SUM_TOL`.
Worked example: same tokens and model, reported total 0.0345 → input 0.006, output 0.0075, cache_read 0.006, cache_write 0.015.
Edge cases: unpriced model with tokens input 1, output 3, total 1.0 → input 0.25, output 0.75; all-zero tokens, total 1.0 → input 1.0.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_allocate.

## C-cost: event cost and cost_basis
First that applies:
1. harness reports per-type USD → those values (reasoning cost already inside output), total = sum, `cost_basis:"reported"`.
2. harness reports only a total → C-allocate, `"reported_total_allocated"`.
3. model priced (C-price-match) → C-list, `"list_price"`.
4. else all five cost fields 0.0, `"unknown"`; analyze counts these calls in `coverage.<harness>.unpriced_calls`. Never a guessed price.
Edge cases: zero tokens with a price → all zeros, `"list_price"`; reported split with missing types → those types 0.0; null model → rule 4.
Worked example: reported `{input:0.1, output:0.2}` → cost `{0.1, 0.2, 0, 0, total 0.3}`, `"reported"`; same tokens, model `mystery-1`, nothing reported → all 0.0, `"unknown"`.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_cost_reported_unknown (rules 1, 4), test_c_allocate (2), test_c_list (3).

## C-cache-ttl: cache writes by TTL
Claude bills 5-minute cache writes at 1.25x input and 1-hour writes at 2x input (matched Claude Code OTel cost to 1e-6). Optional token keys `cache_write_5m`, `cache_write_1h` (ints >= 0) are subsets of `cache_write`, which stays the total, so C-tokens disjointness and every sum over `TOKEN_TYPES` are unchanged. Optional price keys of the same names in prices.json (Claude rows: 1.25x / 2x input).
Formula: `rest = cache_write - cache_write_5m - cache_write_1h` (missing key = 0); `cost.cache_write = (rest * p.cache_write + cache_write_5m * p.get(cache_write_5m, p.cache_write) + cache_write_1h * p.get(cache_write_1h, p.cache_write)) / PER_TOKENS`. Used by C-list and so by C-allocate weights.
Edge cases: no split keys → flat `cache_write` price (unchanged behavior; the flat Claude values are kept as before and are inconsistent: opus = 1h rate, others = 5m rate, so readers with the split should always pass it); model without TTL prices (gpt, gemini) → flat rate; `make_tokens` raises `cache_write` to the split sum if smaller; check.py rejects `cache_write_5m + cache_write_1h > cache_write` at any depth.
Worked example: sonnet (input 3 → 5m 3.75, 1h 6), `cache_write 3500, cache_write_5m 1000, cache_write_1h 2000` → (500·3.75 + 1000·3.75 + 2000·6)/1e6 = 0.017625.
Test: `02-measure/tests/test_schemas.py` Cost.test_c_cache_ttl.

## C-basis-worst: session cost_basis
`BASIS_ORDER = reported < reported_total_allocated < list_price < unknown`. A session's (or any aggregate's) basis is the latest in that order among its api_call events; no events → `unknown`.
Worked example: `[reported, list_price, reported]` → `list_price`.
Formula: `basis = max(bases, key=BASIS_ORDER.index)`, `unknown` if empty. Edge: only api_call events count (user_prompt/tool_decision bases are ignored).
Test: `02-measure/tests/test_schemas.py` Cost.test_c_basis_worst.

## C-sum: cost parts add up
For every object with numeric `total, input, output, cache_read, cache_write` (event, session, totals): `|input + output + cache_read + cache_write - total| <= SUM_TOL` (1e-6 USD). Checked by `check.py` at any depth.
Worked example: `{input:0.1, output:0.2, cache_read:0, cache_write:0, total:0.3}` passes; total 0.31 fails.
Edge cases: an object missing any of the five fields, or with a non-numeric one, is not a cost object for C-sum and is skipped (the schema reports the missing/bad field itself); 5e-7 off passes, 1e-5 fails.
Test: `02-measure/tests/test_schemas.py` Broken.test_session_analysis_decision_impact (session, analysis totals), Fixtures.test_cli_rejects_broken_copy (event via CLI).

## S-event-kind
Rules (event rows):
- `decision` and `decision_source` are non-null only on `tool_decision`; a `tool_decision` has non-null `tool` and `decision`.
- `user_prompt` and `tool_decision` (`ZERO_KINDS` in check.py) have every `tokens` and `cost` value 0: `any(tokens.values()) or any(cost.values())` → error.
- No text field anywhere (the event schema allows no extra keys).
Edge cases: their `cost_basis` is free (use `"unknown"`); an `api_call` with zero tokens is valid.
Worked example: `{kind:"tool_decision", tool:"Bash", decision:"accept", tokens:all 0, cost:all 0}` passes; same with `tokens.input:5` or `cost.input:0.5,total:0.5` fails; `api_call` with `decision_source:"user"` fails.
Test: `02-measure/tests/test_schemas.py` Semantic.test_s_event_kind.

## S-decision-choice
Rule: `set(probabilities) ⊆ set(options)` and `choice in options or choice == "unsure"`.
Edge cases: empty `probabilities` is valid; empty `options` allows only `choice:"unsure"`; probabilities need not sum to 1 (vendor scores).
Worked example: options `{a, b}`, probabilities `{a:0.7, b:0.3}`, choice `a` passes; choice `unsure` passes; probability key `zzz` fails; choice `maybe` fails.
Test: `02-measure/tests/test_schemas.py` Semantic.test_s_decision_choice, Broken.test_session_analysis_decision_impact.

## S-session-order
Rule: `parse(end) >= parse(start)`, both parsed as aware datetimes (`Z` or `±HH:MM` offset, optional fraction), so offsets compare correctly. Writers should still emit UTC `Z`.
Edge cases: `end == start` passes (single-event session); unparseable ts → no S-session-order error (the ts pattern reports it).
Worked example: start `2026-10-01T12:00:00+02:00` (10:00Z), end `2026-10-01T10:30:00Z` passes; start `10:30:00Z`, end `12:00:00+02:00` fails.
Test: `02-measure/tests/test_schemas.py` Semantic.test_s_session_order.

## S-raw-payload
Rule: a v1 raw line (has `v`) has exactly one of `data` (parsed JSON), `undecoded` (summary of a dropped body: bytes, sha256, content_type, reason) and `data_b64` (raw body, base64, only with `KEEP_RAW_UNDECODED`). Legacy lines (no `v`) are not checked.
Edge cases: neither or both → error. `v` must be the integer 1 (const is type-strict: `1.0` or `true` fail).
Worked example: `{v:1, recv_ts, path:"/v1/logs", content_type, harness_hint:null, data_b64:"AA=="}` passes; same without payload, or with both, fails.
Test: `02-measure/tests/test_schemas.py` Semantic.test_s_raw_payload, Semantic.test_const_strict.
