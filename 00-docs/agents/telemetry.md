# Telemetry notes

## What OTel adds over Claude Code transcripts

`cost_usd`, `duration_ms`/`ttft_ms` per API call, `api_error` with retry attempts, `tool_decision` (auto vs user approval, rejections), `active_time`. Everything else (tokens, model, tool use) is already in `~/.claude/projects/*.jsonl`. OTel carries no prompt or response content unless `OTEL_LOG_USER_PROMPTS` is set.

## Pitfalls

- OTLP JSON `intValue` may arrive as a string.
- Each record repeats ~10 identity attributes, including user email: matters for storage size and privacy.
- Agents drop telemetry silently when the endpoint is down (tested on Claude Code: no warning, no delay). `02-measure/coverage.py` measures the gap against local Claude Code transcripts; the collector's `/health` turns `stale` when nothing arrives.
- Nothing is retroactive: data exists only from the moment telemetry is enabled.
