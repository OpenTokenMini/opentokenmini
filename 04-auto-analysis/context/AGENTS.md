# context

Context efficiency from Claude Code transcripts, per session and over the window: context per main-thread turn (growth curve), peak context, compactions with context before and after, cache read / cache write / uncached input shares, estimated cache write cost, identical re-reads of a file, and tool result tokens per tool. Reads usage blocks, `compact_boundary` metadata and `tool_use` / `tool_result` sizes (plus Read/Edit file paths, in memory only to match re-reads). Writes counts only: no file path, prompt, command or tool output. Specs: `METHOD.md` (X-*). Doc: `../context.md`.

- Input: `~/.claude/projects/**/*.jsonl` (or config `readers.paths.claude-code`, or `--root`); prices from `02-measure/schemas/prices.json`.
- Output: `context.json` in the data dir (or `--out`): `readout` (copied by the pipeline into `readout.json` section `context`, < 400 bytes), `aggregate`, `curve_median`, `sessions` (top 20 by peak).
- CLI: `python3 04-auto-analysis/context/context.py [--days N] [--root DIR] [--config PATH] [--out DIR]`
- Pipeline stage `context` (local, optional) in `03-analyze/pipeline.py`. Tests: `../tests/test_context.py`.

## Reconfigure
Constants at the top of `context.py`: `DAYS`, `ROOT`, `CHARS_PER_TOKEN`, `IMAGE_TOKENS`, `THRESHOLDS`, `CURVE_TURNS`, `CURVE_POINTS`, `TOP_TOOLS`, `TOP_SESSIONS`, `EDIT_TOOLS`, `MAX_READOUT_BYTES`. Other harnesses are not read yet: add a `scan` returning the same per-file records.

## Adapt, trade-offs, decisions for the human

- Adapt: `THRESHOLDS` to the model's window; `CHARS_PER_TOKEN` for code-heavy output.
- Trade-offs: costs are list-price estimates; tool result tokens are chars/4 and counted once although they stay in context for every later turn; a re-read only counts when path, offset and limit are identical and no edit to that file happened in between.
- Decisions for the human: whether to compact or start fresh sessions earlier, cap noisy tool output (Bash, MCP), or change cache TTL.
