# quality

First working reader of `../quality.md`: per session and per commit, local quality signals computed from Claude Code transcripts and local git. It classifies every shell command into the risk classes `../quality.md` names first (destructive, data exfiltration, secrets), and adds test runs (pass/fail), tool error rate and rework. Commits join sessions through `impact.jsonl`. Specs: `METHOD.md` (Q-*).

- Input: Claude Code transcripts (`~/.claude/projects/**/*.jsonl`, or `readers.paths.claude-code`); `impact.jsonl` from the data dir (optional: without it there are no commit records); `git log --name-only` of the repos found from `--repo`, config `impact.repos`, session cwds and edited files' dirs.
- Output: `quality.jsonl` (one record per session and per linked commit), `quality_summary.json` in the data dir (or `--out`).
- CLI: `python3 04-auto-analysis/quality/quality.py [--days N] [--repo PATH ...] [--config PATH] [--out DIR] [--impact FILE] [--transcripts DIR]`
- Data touched: reads tool calls and tool results in memory (command text, result text, edited file paths) to classify them; writes only counts, rates, pass/fail, session ids, commit shas and timestamps. No command text, output, file path or content is written. Read-only on git; no network.
- Run after `impact` (it joins on impact's linked commits): pipeline stage `quality` (local, optional, after `impact2`) in `03-analyze/pipeline.py`; its summary goes to section `quality` of `readout.json`.
- Record schema: proposed in `../tests/fixtures/quality/quality.schema.json` (same conventions as `02-measure/schemas`: `v: 1`, ISO UTC, `repo_label` = basename as in impact). Move it to `02-measure/schemas/` when a downstream stage reads it.

Tests: `../tests/test_quality.py` (fixture transcripts in `../tests/fixtures/quality/claude/`, temp git repo, no network).

## Reconfigure

Constants at the top of `quality.py`: `DAYS`, `ROOT`, `REWORK_HOURS`, `SHELL_TOOLS`, `EDIT_TOOLS`, `TEST_RX`, `FAIL_RX`, `RISK_RX`, `LOCAL_RX`. No config key yet (adding one means adding `quality` to `DEFAULTS` in `02-measure/schemas/config.py`).

## Adapt, trade-offs, decisions for the human

- Adapt: `TEST_RX` to the team's test commands; `RISK_RX` to what the team counts as risky; `REWORK_HOURS` to its commit rhythm.
- Trade-offs: Claude Code only (other harnesses log tool results differently; next). Risk classes are regexes, so they over- and under-match; they are counts to look at, not verdicts (a decision model per command is the next step, `../quality.md`). Commit rework is file-level, an upper bound: in doc-heavy repos where every commit touches the same `AGENTS.md`, it is high. Permission decisions (risky approval without review) are not read yet.
- Decisions for the human: whether reading command and result text in memory is acceptable at this measure level (nothing of it is written); which repos may be scanned.
