# orch-ux

UX of the orchestrator (the main Claude Code agent talking to the human), so it can calibrate how much it reports and nudge itself. Per human turn: user words, words of the final visible reply (text after the last tool use), tool calls, subagents launched, duration, and how the human reacted next: correction, more, neutral, interrupt or reject. Derives a target reply length from the data and rule-based nudges. Specs: `METHOD.md` (U-*).

- Input: main transcripts `~/.claude/projects/*/<sid>.jsonl` (or config `readers.paths.claude-code`, or `--root`); worker transcripts `<sid>/subagents/agent-<id>.jsonl` only for their peak context. Optional: local decision model d1 at `D1_URL` to refine correction / more / neutral.
- Output: `orch_ux.json` in the data dir (or `--out`): `generated`, `window_days`, `classifier`, `overall`, `calibration`, `nudges`, `sessions` (20 newest), `turns` (last 40), `workers` (worker -> orchestrator reports: size, partial, over budget, missing hash/tests, follow-up calls; nudge ids `workers_*`). Snippets of user text and reply (80 chars) are written. The pipeline copies `readout(r)` to `readout.json` section `orch_ux`.
- CLI: `python3 04-auto-analysis/orch-ux/orch_ux.py [--days N] [--root DIR] [--config PATH] [--out DIR] [--d1] [--no-d1] [--eval [PATH] | --holdout | --test2]` (`--eval`: baseline vs heuristic vs d1 vs combined accuracy on `tests/data/classify_eval.jsonl`; `--test2` is the untouched test set; `--d1` lets d1 flip neutral -> more in the scan)
- Pipeline stage `orch_ux` (local, optional) in `03-analyze/pipeline.py`, after `context`. Tests: `tests/test_orch_ux.py`.
- Live use: the UserPromptSubmit hook `../../06-optional/hooks/orch-nudge.py` reuses `parse` / `heuristic` on the current session.

## Reconfigure
Constants at the top of `orch_ux.py`: keyword lists `VISIBLE_THEME`, `LENGTH_THEME`, `CORRECTION`(+`_RX`), `MORE`(+`_RX`), `SHORT_Q_WORDS`; d1 (opt-in `--d1`) `D1_URL`, `D1_TIMEOUT`, `D1_MORE_CONF`, `D1_MAX_CALLS`; calibration `TARGET_PRIOR_WORDS`, `PRIOR_N`, `TOLERANCE`, `MIN_REPLY_WORDS`; nudge thresholds `LONG_REPLY_SHARE`, `VISIBLE_REPEAT_MIN`, `LENGTH_COMPLAINTS_MIN`, `LONG_CHAIN_TOOLS`, `LONG_CHAIN_MIN`, `ASK_BACK_SHARE`, `ASK_BACK_MIN`, `MORE_SHARE`; workers `PARTIAL_RX`, `COMMIT_RX`, `TESTS_RX`, `BUDGET_RX`, `FOLLOWUP_MANY`, `*_RATE_MAX`, `FOLLOWUP_P50_MAX`, `WORKER_MIN`.

## Trade-offs, decisions for the human
- Keyword heuristics are ES+EN and substring based: a new request that happens to contain "por qué" counts as a correction. d1 (when up) decides only messages without an explicit visible/length theme.
- Reply words count only the text after the last tool use, so progress text between tools is not counted.
- Decisions for the human: the prior target (`TARGET_PRIOR_WORDS`) and whether to install the hook.
