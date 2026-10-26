# orch-ux: specs

Constants at the top of `orch_ux.py` (`DAYS=7`, `TARGET_PRIOR_WORDS=120`, `PRIOR_N=10`, `TOLERANCE=0.25`, ...).

## U-scan
Every `<project>/<sid>.jsonl` under the root modified at or after since (main threads; `subagents/` not globbed); `isSidechain` lines skipped. Turns whose human message is before since are dropped. `sid` = first 8 chars of the file name. Session name: last `custom-title`, else `agent-name`, else `ai-title`, else the first human text (40 chars).

## U-human
A real human message: `type=user`, not `isMeta` / `isCompactSummary`, no `tool_result` block, text not starting with `<` (task-notification, command-name, local-command-*, system-reminder), `This session is being continued`, `Caveat:` or `/`, and not an interrupt marker. A prompt starting with `<pasted_content` is human (the paste is ignored by U-classify). Automated, not human: `entrypoint` `sdk-cli` (`AUTO_ENTRYPOINTS`), `origin.kind` other than human (`HUMAN_ORIGINS`: task-notification, peer messages), text starting with `AUTO_PREFIX` (heartbeats).

## U-turn
From one human message to the next. `tool_calls` = tool_use blocks; `subagents` = those named `Agent`/`Task`; The response to the human ends at the first system `turn_duration` (`TURN_END`) or the first automated user text (notification, heartbeat, reminder); assistant lines after that until the next human message are not part of the turn. `reply_words` = whitespace words of assistant text after the last tool_use, fenced code excluded; `code_words` = words inside the fences; `min` = last timestamp in the turn minus the human message's; `asks` (internal) = the reply ends with `?`.

## U-next
How the turn ended, first that applies: a tool_result containing "The user doesn't want to proceed" / "tool use was rejected" -> `reject`; a user text with `[Request interrupted by user` -> `interrupt`; else the next human message classified (U-classify); none yet -> null.

## U-classify, U-d1
Lowercased: `VISIBLE_THEME` -> correction (theme visible); `LENGTH_THEME` -> correction (theme length); `CORRECTION`/`CORRECTION_RX` -> correction; `MORE`/`MORE_RX`, or a question of at most `SHORT_Q_WORDS` words -> more; else neutral. d1 is off by default (`--d1` turns it on for the scan): when on, it is asked only when the heuristic says neutral with no theme (POST `D1_URL`, `{state, q, type:"choice", opts:[[name, description], ...]}`), and its answer counts only if it is "more" with confidence >= `D1_MORE_CONF`; the heuristic alone decides correction. The first error or timeout (`D1_TIMEOUT`) turns d1 off for the run. `classifier` = "d1" if at least one d1 answer was used.

## U-overall
Counts of `next` kinds; reply percentiles over turns with a visible reply (> 0 words); tools and minutes over all turns; `turns_with_code`, `code_words_p50` (over turns with code). Percentile = sorted value at index int(q * n).

## U-calib
target = (TARGET_PRIOR_WORDS * PRIOR_N + p50(neutral replies) * n_neutral) / (PRIOR_N + n_neutral); if any length complaint, target = min(target, p25(replies complained about) * (1 - TOLERANCE)); at least `MIN_REPLY_WORDS`. verdict: current p50 > target * (1 + TOLERANCE) too_long, < target * (1 - TOLERANCE) too_short, else ok. `why` cites the counts.

## U-nudge
long_replies (share over target*(1+TOL) >= LONG_REPLY_SHARE), verify_visible (visible-theme corrections >= VISIBLE_REPEAT_MIN), length_complaints (>= LENGTH_COMPLAINTS_MIN), long_chain (interrupts/rejects after >= LONG_CHAIN_TOOLS tool calls, >= LONG_CHAIN_MIN), ask_back (replies ending in `?` >= ASK_BACK_MIN and share >= ASK_BACK_SHARE), too_short (info: share followed by more >= MORE_SHARE), corrections (info, only when nothing else fired). `evidence` cites counts.

## U-workers
Finished workers per main transcript in the window: a user message with `<task-notification` (`task-id`, `tool-use-id`, `status`, `result`, `subagent_tokens`) or a sync `Agent`/`Task` tool_result that is not the launch ack (`ASYNC_ACK`); last result per agent id. Prompt and description come from the launching tool_use. Per worker: `report_words`/`report_chars` of the result; `partial` = status not `completed` or `PARTIAL_RX`; `ctx_limit` = `CTX_LIMIT_RX`; `commit` = `COMMIT_RX` (hex 7-40 with a digit and a letter); `tests` = `TESTS_RX`; `budget` = `BUDGET_RX` on the prompt (`N` k); `peak_ctx` = max input + cache read + cache write over the assistant messages of `<sid>/subagents/agent-<id>.jsonl`, else `subagent_tokens`; `over_budget` = peak_ctx > budget; `gaps` = commit/tests asked by the prompt (`ASK_COMMIT_RX`, `ASK_TESTS_RX`) and absent from the report; `followup_calls` = orchestrator tool_use blocks after the result until its next non-empty text, a human message or another notification.
Section `workers`: n, report_words_p50, partial_rate, over_budget_rate (of `with_budget`), gaps_rate (of reports whose prompt asked), followup_calls_p50, peak_ctx_p50, examples (<= `WORKER_EXAMPLES`, scored 2*partial + over_budget + gaps + followup >= `FOLLOWUP_MANY`). Nudges (>= `WORKER_MIN` workers): workers_partial (partial_rate > `PARTIAL_RATE_MAX`), workers_over_budget (> `OVER_BUDGET_RATE_MAX`), workers_report_gaps (> `GAPS_RATE_MAX`), workers_followup (p50 > `FOLLOWUP_P50_MAX`).

## U-eval
`tests/data/classify_eval.jsonl` (local only, gitignored: real prompts): 25 follow-up human prompts from the 7 days before 2026-10-25, hand-labelled (15 correction, 1 more, 9 neutral; excerpts <= 120 chars). `--eval` prints accuracy. Run on 2026-10-25 (d1 at `D1_URL`): heuristic 21/25 (correction 12/15, more 1/1, neutral 8/9); raw d1 14/25 (correction 5/15, more 1/1, neutral 8/9); combined with `D1_MIN_CONF` only 19/25 (d1 overturned 2 heuristic corrections to neutral at 0.73 and 0.78). d1 is worse on correction, so `D1_OVERRIDE_CONF = {"correction": 0.95}`: d1 needs that confidence to overturn a heuristic correction. Combined after: 20/25 (correction 12/15, more 1/1, neutral 7/9). (`D1_MIN_CONF`/`D1_OVERRIDE_CONF` were replaced by `D1_MORE_CONF` in round 3.)

## U-readout
`readout.json` section `orch_ux`: turns, reply_words_p50, target_reply_words, verdict, corrections, interrupts, rejections, nudge ids, detail.

## U-ex (tests/test_orch_ux.py)
Turn 1: Bash + Agent, reply "Listo, el botón ya aparece en la home." = 8 words, 3.0 min, then "sigo sin ver el botón" -> correction (visible). A task-notification, a local-command caveat and a compact summary are not turns. Turn 2 ends in a rejected tool_result -> reject; turn 3 in an interrupt; turn 4 "y el color?" (itself a more-style message) gets a reply ending in `?`, then "ok" -> neutral; turn 5 -> null.

Recalibration 2026-10-25 (batch 2): 27 more real prompts appended (rows with `"added": "2026-10-25 batch 2"`; now 52: 30 correction, 5 more, 17 neutral). Before rule fixes on all 52: heuristic 32, raw d1 33, combined 34; the old heuristic got only 11/27 on the unseen rows (overfit to the first 25). Added rule gaps seen in real prompts (`VISIBLE_RX` "roto"/"no llega", "mas breve", "me refiero", "nunca más", `^falta`, "se fue", "estás seguro"). After: heuristic 44/52, raw d1 33, combined 43 (optimistic: the new rules were written looking at these rows). Known misses kept: negative-imperative instructions, short follow-ups without "?", slang.
Held-out (`tests/data/classify_holdout.jsonl`, `--holdout`): 60 real follow-up prompts, one random prompt per random main transcript modified 2026-09-01..2026-10-16 (before the in-sample window), none in `classify_eval.jsonl`; synthetic bus-agent prompts ("Read the bus ...", replies about `/work/`) excluded; text <= 300 chars. Labelled by hand before any classifier ran (18 correction, 12 more, 30 neutral). Run 2026-10-25, no rule changed: heuristic 34/60 (correction 4/18, more 0/12, neutral 30/30), raw d1 34/60 (correction 5/18, more 7/12, neutral 22/30), combined 34/60 (correction 4/18, more 2/12, neutral 28/30). Always-neutral scores 30/60, so the heuristic adds 4 points out of sample against 44/52 in-sample: it never fires falsely but misses most corrections. Labels are one person's judgement; correction-vs-neutral on "do X instead" tweaks and more-vs-neutral on follow-up questions are the soft spots.
Rule-gap candidates from the held-out misses (applied in round 3 below): openers that redirect ("está bien, pero", "sí, pero", `^pero `, `^digo`, "a lo que voy", leading `^sin `); "sigue con" (problem persists); "no sirve", "no entiendo", "no estás respetando", "te fuiste a"; frustration words as a correction signal; for more: "por ejemplo", "y si ...?", short questions on the previous answer, where d1 does better (7/12) than the heuristic (0/12), so letting d1 override neutral -> more is a candidate too.
Reply words (U-overall): only the final reply after the last tool call counts, fenced code blocks excluded (`reply_words`). The 89 target is derived: 3 "too long" complaints cap it at p25 of their lengths * (1 - TOLERANCE); only `TARGET_PRIOR_WORDS` is a guess.
Report gaps (U-workers): `TESTS_RX` missed "suite passes (75 tests)", "57 tests OK" and Spanish "pasan los tests": flagged 14/64, 6 true by eye (43%); after the fix 8 flagged, 6 true (75%; the 2 false: tests mentioned only as "orchestrator runs tests", "fixtures all pass").

Round 3 (2026-10-25), protocol: the held-out set had been read to list the rule gaps above, so it no longer measures out of sample. (1) A fresh `tests/data/classify_test2.jsonl` (`--test2`): one random prompt per random main transcript over the whole history (seed 20261025), none in the other two files, text <= 300 chars, bus-agent prompts and 3 synthetic "test" prompts dropped; 39 rows labelled by hand and committed before any classifier ran on them (11 correction, 7 more, 21 neutral). (2) Tuning on dev + former holdout (112 rows, both training now): general rules only (redirecting openers `^(está bien|sí|ok|dale), pero`, `^pero`, `^digo`, "a lo que voy", leading `^sin `; "sigue con", "no sirve", "no entiendo", `respet[aá]`, "te fuiste"; frustration words; "más corta"; for more: "por ejemplo", `^y si ...?`, `^y` + 1-3 words, short questions); combination: heuristic decides correction, d1 may flip neutral -> more at `D1_MORE_CONF` = 0.65 (best single threshold on training; letting d1 also flip to correction or back to neutral gained 3 more training rows with two extra thresholds, not taken). (3) One run on test2.
Results (accuracy; per-class recall correction / more / neutral):
- dev (52, training): baseline 17; heuristic 44 -> 47; combined 47 (28/30, 4/5, 15/17).
- former holdout (60, now training): baseline 30; heuristic 34 -> 49 (16/18, 7/12, 26/30); raw d1 34; combined 50 (16/18, 8/12, 26/30). In-sample, so optimistic.
- test2 (39, never tuned on): always-neutral 21/39 (0/11, 0/7, 21/21); old heuristic (before round 3) 25/39 (3/11, 1/7, 21/21); new heuristic 27/39 (4/11, 3/7, 20/21); raw d1 24/39 (4/11, 3/7, 17/21); combined 27/39 (4/11, 3/7, 20/21).
Reading: the heuristic beats always-neutral by 6 of 39 out of sample, and the round-3 rules add 2 of those; correction recall stays low (4/11) because most corrections in fresh prompts carry no fixed phrase ("whistle, no whisper", "Opus 5.5 en vez de Claude"). d1 added nothing on test2, so the default is the heuristic alone and d1 is opt-in (`--d1`). With n = 39 a 2-row difference is noise; the stable finding is "few false corrections, most real ones missed".

Word-count audit (2026-10-25, 7 days, U-human / U-turn). Before: 321 turns, reply p50 127 / p90 241, 41 corrections. Miscounts: 16 turns had the reply to a later notification or heartbeat counted as the reply (e.g. "pushea": 61 counted, 278 real); 11 human prompts starting with `<pasted_content` were skipped and merged into the previous turn; 2 scripted `sdk-cli` turns counted as human; the reply to an isMeta reminder ("No response requested.") was appended to the previous reply. After the fix: 331 turns, p50 121 / p90 235, 43 corrections, 10 turns with code (code p50 12 words); target 89 unchanged. Sample, 12 turns (6 random among changed, 6 among unchanged, seed 20261025), reply words old -> new:

| prompt | old | new | why |
|---|---|---|---|
| #1 | 60 | 60 | |
| #2 | 95 | 95 | 28 code words apart |
| #3 | 490 | 295 | notification reply counted |
| #4 | 166 | 69 | next prompt was a paste, merged |
| #5 | 199 | 54 | notification reply counted |
| #6 | 577 | 110 | notification reply counted |
| #7 | 218 | 294 | notification reply counted instead of the real one |
| #8 | 224 | 294 | same |
| #9 | 102 | 102 | |
| #10 | 145 | 145 | |
| #11 | 40 | 40 | |
| #12 | 203 | 203 | |

## Audit 2026-10-25b: session e3073449 (otm-orque), hand-labelled
Fixes: "Resumed by another session" prompts are automated; queued prompts with no reply in between merge into one turn; harness `<synthetic>` assistant text ("No response requested.") is not a reply; "qué pasó"/"what happened" is a correction. Turns 21 -> 18, reply p50 147 -> 168, corrections 3 -> 4, rejects 1, interrupts 0, more 1.
On 17 labelled reactions: correction P 4/4, R 4/6 (before 3/3, 3/6); reject 1/1; more 1/1 (borderline). Left out (overfit): a comparative redirect and a fact correction.
Replies to heartbeats/notifications stay out: in the unsupervised run the human did not read them live, and they answer the cron, not the human.
