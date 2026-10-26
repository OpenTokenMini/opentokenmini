# hooks

Claude Code hooks built on the analyses. Not installed by anything: the human adds them to a settings file.

- `orch-nudge.py` UserPromptSubmit hook. Reads the hook JSON on stdin (`transcript_path`, `prompt`), parses the tail of the current session with `04-auto-analysis/orch-ux/orch_ux.py` heuristics (no network, < 300 ms), treats the incoming prompt as the reaction to the last reply, and prints at most 2 `[orch-nudge] ...` lines only when a rule fires (stdout of a UserPromptSubmit hook is added to the agent's context); otherwise nothing. Fills the second line from the latest `orch_ux.json` warn nudges in the data dir. Any error: silent, exit 0.
- Rules (constants at the top): last reaction "sigo sin ver"-style -> verify before reporting; "muy largo"-style -> shorter; interrupt/reject after >= `CHAIN_TOOLS` tool calls; p50 of the last `LAST_N` replies over the calibrated target (from `orch_ux.json`, else `TARGET_PRIOR_WORDS`); >= `ASK_BACK_MIN` of the last `ASK_BACK_RECENT` replies end with a question; `workers_partial`: finished workers of this session (`<transcript>/subagents/agent-*.jsonl` modified in the last `WORKER_WINDOW_S`, last assistant message text-only) graded with `orch_ux.grade` as partial, or whose peak context (tail usage) exceeds the budget stated in their prompt.
- Tests: `tests/test_orch_nudge.py`.

## Install (human decision)
Add to `~/.claude/settings.json` (or a project's `.claude/settings.json`), with the absolute path of this repo:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 /ABS/PATH/opentokenmini/06-optional/hooks/orch-nudge.py", "timeout": 5}]}
    ]
  }
}
```

Refresh the global nudges by running the pipeline (stage `orch_ux`) or `python3 04-auto-analysis/orch-ux/orch_ux.py`.
