# Context efficiency

First reader working: [`context/`](context/AGENTS.md) (Claude Code transcripts). How much context sessions carry, how it grows, and what fills it.

- Reads: per-call token usage (uncached, cache read, cache write), compaction markers, tool result sizes. Never prompt or tool content in the output.
- Used for: when to compact or start fresh, which tools flood context, what cache writes cost.

## Flags

- sessions over 150k/250k context (cost per turn grows with it; quality drops near the window)
- the same file read again unchanged
- one tool (often Bash or an MCP server) dominating result tokens
- cache writes a large share of cost (short sessions, cache expiring between turns)

## Pitfalls

- Token counts of tool results are chars/4 estimates; usage counts are exact.
- A result stays in context on every later turn, so its real cost is higher than its size.
- Other harnesses (Codex, OpenCode) log usage differently; not read yet.
