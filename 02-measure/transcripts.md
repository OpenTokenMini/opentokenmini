# Full transcripts (opt-in)

Placeholder. Pushes a copy of each harness's local session logs (for Claude Code, `~/.claude/projects/*.jsonl`) to the collector.

- Input: local session log files.
- Output: the same files, unmodified, stored next to telemetry records.
- Data it touches: everything in the session, including prompts, code and tool output. Off by default; the owner enables it explicitly and every user is told.

Also the fallback for harnesses without native OTel.
