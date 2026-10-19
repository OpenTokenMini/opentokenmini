# decide: decision point specs

Constants live at the top of `decide.py` and `decision_points.py`; questions, options and rubrics in `points.json`. Tests: `06-optional/tests/test_decide.py`.

## D-state
State sent with each question: one intro sentence + compact sorted-key JSON of facts, cut at `MAX_STATE_CHARS` (6000 chars, ~1.5k tokens). Facts are numbers already in sessions.jsonl / analysis.json / impact.jsonl; no prompt text, paths or repo names except `repo_label`. Cost mix = part / cost.total per type (input, output, cache_read, cache_write), 3 decimals, 0 when total is 0. Cache hit = cache_read / (input + cache_read + cache_write), null when the denominator is 0 (same as analyze M-cache-hit-rate). Lists: top `TOP_TOOLS` tools by calls, top `TOP_MODELS` models by cost.

## D-cache
`state_sha` = sha256 of JSON `[state, question, options, kind]` (sorted keys), first 16 hex. A (point, state_sha) present in decisions.jsonl is never asked again; vendor is not part of the key. Changing a rubric or any fact changes the sha and asks again. Duplicate items in one run are asked once.

## D-pick
choice = top option if p(top) - p(second) >= `MIN_LEAD` (0.2), else `"unsure"`. Ties broken by option name. Single option: lead = p. Example: {a:.5, b:.3, c:.2} -> a; {a:.45, b:.35, c:.2} -> unsure; {yes:.9, no:.1} -> yes.

## D-outlier-explanation
One `choice` item per `analysis.outliers[i]`. Facts: metric id and definition, group, value, group median (baseline), robust z, group n, and the session facts (D-state) when `session_id` is in sessions.jsonl. Subject `<metric>:<group>:<session_id|->`. Options: `points.json` outlier_explanation. Result in `analysis.decided.json` as `outliers[i].decision = {choice, probabilities, state_sha, vendor}`. Missing session: asked with outlier facts only.
D-outlier-model: facts also carry `baseline` (`model` when the group is `<harness>/<model>`, `harness_fallback` when the group is the whole harness; then also `baseline_typical_model` = most common main model in that harness and its price tier), and, with a session, `main_model` (most-cost model), `main_model_list_usd_per_mtok` {input, output} from schemas/prices.json and `main_model_price_tier` by output price: <= 1 budget, <= 15 standard, else premium, no price -> unpriced. Without these, an expensive model scored against a cheap fallback median was labelled agent_loop.

## D-recommendation
One `noul` item per (candidate, harness): every `analysis.recommendations` entry (its `evidence` added to facts) plus every catalog candidate in `analyze/metrics.json` `recommendations` (single source; `points.json` holds only the question) for each harness that has sessions and whose id is not already listed. Facts: harness aggregates from sessions.jsonl (sessions, cost, cost mix, cache hit, turns, calls, calls per turn, median session cost, subagent share, model cost share, MCP error rate). harness null -> all sessions. Subject = the recommendation id (`<candidate id>/<harness>`, the same id analyze writes, so a candidate is asked once per harness). Applied: `p_yes` = p(yes); verdict `suggest` if p_yes >= `SUGGEST_P` (0.7), `skip` if <= `SKIP_P` (0.3), else `unsure`; not yet answered -> p_yes and verdict null. Catalog candidates are appended with that id and evidence `cost_share.<type>`. Items for the same harness share a state, so a batching vendor answers them in one request.

## D-commit-link
One `noul` item per impact.jsonl record with `link:"window"`, `link_p:null`, non-empty `commits`, and its session in sessions.jsonl. Facts: session harness, start, end, active minutes, calls, turns, edit tool calls (`EDIT_TOOLS` in decision_points.py: file-editing tools only, shown to the model as evidence of edits; unlike impact `WRITE_TOOLS`, which adds shell tools because L-assign only needs "could have run `git commit`"), and per commit ts, files, added, deleted, agent_trailer, on_default_branch. Subject = L-subject in impact/METHOD.md. Runs whenever such records exist (impact needs it), regardless of `decide.points`. Impact reads `probabilities.yes` from decisions.jsonl (point commit_link, matching subject) as link_p and drops it below its MIN_P. Ledger tag `impact`.

Contract impact<->decide (commit_link): kept in one place, impact/METHOD.md L-subject.

## D-intent
Reserved. Needs prompt text, which v002 events never carry; listing `intent` in `decide.points` stops the run.

## D-apply
`analysis.decided.json` = deep copy of analysis.json with D-outlier-explanation and D-recommendation applied, validated against the analysis schema. analysis.json is never written. Each run asks at most `MAX_CALLS` questions (`--max-calls`); the rest stay unanswered until the next run. The first vendor error stops asking; answers so far are kept.
