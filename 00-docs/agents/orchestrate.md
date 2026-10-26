# Orchestrating work on this repo

How a main session builds OpenTokenMini by delegating to subagents in short loops, using its own telemetry (`otm-live` MCP, `06-optional/mcp-server/live.py`) to manage context, time and quota. Rules below come from measured sessions; see [Evidence](#evidence) for numbers and method.

## Agents (`.claude/agents/`)

| agent | model | use for | context budget | returns |
|---|---|---|---|---|
| `otm-worker` | opus | one change in one component: code, tests, AGENTS.md, commit | plan for ≤60k | ≤120 words + commit |
| `otm-reviewer` | opus | verify one commit against its criteria | ~60k | PASS/FAIL per criterion |
| `otm-scout` | sonnet | one factual lookup | ~30k | ≤80 words + paths |

`otm-worker.md` asks for ≤60k because on the measured machine a `ctx-guard` hook (`~/.claude/hooks/ctx-guard.py`, user config, not in this repo) warns subagents at 60k and denies tools at 80k, except writing a handoff. A worker that hits it stops mid-task.

## Worker prompt contract

Every worker prompt today that landed cleanly had the same six parts, ~1.5-2.3k chars:

1. Role + read list: `otm-worker.md`, root `AGENTS.md`, the component's `AGENTS.md`, and the 2-4 files it will copy or touch. Name them; don't say "explore".
2. Isolation: `git worktree add /tmp/otm-wt-<name> -b wt/<name>`, work only there.
3. Ownership: "You own ONLY <dirs/files>. Do not edit <dirs> (<who> is editing them in parallel)." Naming the parallel neighbour is what keeps workers out.
4. Goal + 2-4 checkable criteria, at least one of them a real run on real data with a number to report.
5. Hard rules: never delete (todelete/), no push, session line in the commit message.
6. Return contract: "Return ≤N words: hash, branch, <the 1-3 numbers you need>, unverified." Ask for "not done / out of scope" explicitly; that list is the next batch.

One item = one deliverable set that fits ≤60k. The one prompt today with six deliverables (code, HTTP endpoint, tests, MCP registration, docs, commit; 5.2k chars) is the one that hit the guard and needed a second worker.

## Ownership and merging

- One worktree per worker, one owner per directory. The orchestrator creates worktrees up front (`for n in ...; do git worktree add -q /tmp/otm-wt-$n -b wt/$n; done`) or the worker does it as step 1.
- Shared index files (a component table in a parent `AGENTS.md`, `repo-map.md` Status, root `AGENTS.md`) belong to nobody during a batch. The orchestrator adds the row after merging (`sed -i '/^| `prev\/` /a | ...'`, commit), or one later "reconcile" worker owns all of them.
- Merge on each completion notification: `git merge --no-edit wt/<name>`, then run that stage's tests (full loop after a pipeline or shared-code merge). Don't wait for the batch.
- A 1-line integration bug found after a merge: fix it yourself and commit. Anything larger: a new worker.
- Don't edit a file a running worker owns, even a one-line fix; use a different route or wait.

## Contracts between parallel workers

If worker B consumes what worker A produces in the same batch, write the interface into both prompts: file name, location, keys, and what "missing/skipped" looks like. Without it B guesses. Today the pipeline worker wrote `readout.json`; the parallel dashboard worker, told only "read those summaries as optional files", guessed `deployments_summary.json`, and a reconcile worker ($0.55) had to rewire it. The reconcile prompt that fixed it pasted the exact keys; that is the pattern.

When the interface is not decided yet, run A first and paste its result into B's prompt rather than parallelising.

## Loop

1. `overview` (otm-live): quota left, live sessions, subagents with ctx/cost, overlaps. Stop delegating when 7d utilization reaches the human's target or 5h is near its limit.
2. Pick items from Status in `repo-map.md`, the human's list, or the previous batch's "not done" lines. Group into a batch of items with disjoint owned paths.
3. `declare` the paths; `who_touches` before starting a worker on paths near a live one.
4. `record` phase=start (item, agent, topology), spawn workers in background with the contract above.
5. On each notification: merge, test, add index rows, `record` phase=end (tokens, commit, tests_pass, accepted). Reviewer only for shared code, data contracts or public surfaces.
6. A worker that stopped at the guard: spawn a new one with the handoff path (`/tmp/claude-1000/handoffs/<id>.md`), the resolved facts it asked about, and only the pending steps. A reviewer FAIL: one fix round with the defects pasted; second FAIL, park it and tell the human.
7. Next batch from the "not done" lines. Compact the main session between batches (`/compact <short handoff>`); today's orchestrator stayed ≤73k with 2 compacts over 12 merges.

The main session reads summaries, `git show --stat`, test tails and otm-live, not implementation files.

## What wasted tokens

- Workers past 100k ctx. Across 152 completed workers, the 10 that passed 100k had median cost $9.28 vs $0.55 under 60k and $1.10 at 60-100k; in the session without the guard they were 10 of 59 workers and $171 of $233.
- Long multi-deliverable prompts. Prompt length correlates with cost (Spearman 0.40, n=150 Opus workers): median $0.52 under 1.2k chars, $0.71 at 1.2-2k, $1.31 at 2-3k, $1.90 above 3k. Confounded with task size; the fix is splitting the item, not trimming words.
- Result size limits are overshot but cheap: "≤120 words" returned median 160 words today, 287 in a session that asked for "~250". Result length does not track worker cost (Spearman 0.03). It costs orchestrator context only; keep the limit and ask for numbers, not prose.
- A planner returning 3,110 words (one session) cost the orchestrator more context than ten workers' results.
- Expensive orchestrator model with long context: one session ran the orchestrator on Fable to 258k peak, $61; today's Opus orchestrator ran $2.95 for 12 landed items.

## Delegation ledger

`$OTM_DATA_DIR/delegations.jsonl`, written only by the otm-live `record` tool (the code in `live.py` is the truth):

- `record phase=start item=<id> [agent desc topology]` before launching the worker: stores the start ts and `quota_before` in `<data dir>/live/pending.json`.
- `record phase=end item=<id> [tokens commit tests_pass accepted]` after it returns: appends one line and clears the pending entry. Fields given at end override those from start.

Line: `{"ts", "agent", "desc", "item", "topology", "quota_before", "quota_after", "tokens", "commit", "tests_pass", "accepted"}`. `ts` is the start time; `quota_*` map each window to utilization percent (`{"5h": 41, "7d": 63}`, null when quota is unreadable); missing fields are null. `overview` shows the last lines.

`topology` is a short label of how the item was split (`single`, `worker+review`, `parallel:3`, `scout+worker`). Comparing `tokens`, `tests_pass` and `accepted` per topology is how the pattern gets tuned; new numbers in this doc come from this file or from the method below.

## Evidence

Four Claude Code sessions on one machine, 172 background subagents, 152 completed (last text block ≥60 words; the rest were interrupted by the user or still running when measured, 2026-10-25).

| session | date | workers (done) | worker $ total / median / p90 | median prompt chars | median result words | median peak ctx | >100k ctx |
|---|---|---|---|---|---|---|---|
| e3073449 (this repo, worktrees) | 10-25 | 21 (13) | 12.62 / 0.55 / 1.03 | 1863 | 160 | 44k | 0 |
| d097e3dc (v002 build, guard added mid-session) | 10-18 | 75 (67) | 50.18 / 0.59 / 1.14 | 1153 | 287 | 46k | 1 |
| af2aa24c | 09-28 | 17 (16) | 12.16 / 0.59 / 1.46 | 1761 | 285 | 59k | 3 |
| 6400f535 (no guard, some Fable workers) | 09-19 | 59 (56) | 232.70 / 1.10 / 9.59 | 1674 | 153 | 65k | 10 |

Today (e3073449): batches of 1, 3, 6, 2 and 10 workers; 11 worktree merges, 0 conflicts (`CONFLICT` and `Automatic merge failed` absent from tool results); rework: 1 continuation worker (guard stop), 1 reconcile worker (missing contract), 1 one-line fix by the orchestrator; 3 index rows added by the orchestrator. Workers ran 1-9 min wall time. The data does not show whether batches of 6 or 10 are better; both merged cleanly.

Method (scripts kept outside the repo; reproduce from these definitions):

- Source: `~/.claude/projects/<project>/<sid>.jsonl` and `<sid>/subagents/agent-*.jsonl` + `.meta.json`.
- Assistant messages deduplicated by `message.id`. Peak ctx = max of `input + cache_read + cache_creation` tokens per message.
- Cost = usage × `02-measure/schemas/prices.json` via `schemas/cost.py` `price_for`, cache writes split by 5m/1h TTL when present. List prices; `opus-5-5` rates are fitted, so dollar figures are estimates; ratios between workers are the reliable part.
- Prompt = first user message of the subagent; result = words in its last non-empty text block.
- Merges, conflicts and rework from the orchestrator's Bash tool_use inputs, tool results and task-notification summaries.
