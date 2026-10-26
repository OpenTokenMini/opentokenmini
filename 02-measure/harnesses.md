# Harness telemetry

How to get per-call usage out of each coding agent (harness) into the collector. Nothing else about the harness changes. Two paths per harness: past usage from its local session logs (`from-transcripts.py`, read-only, after the fact) and live telemetry to the collector (per call, as it happens).

## Coverage (tentative priority, not measured market share)

| Harness | Live | Past (`from-transcripts.py`) | Status |
|---|---|---|---|
| Claude Code | native OTel: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_*`; see `claude-code-with-telemetry` | `~/.claude/projects/` | working |
| Codex CLI | native OTel: `[otel]` in `~/.codex/config.toml` | `~/.codex/sessions/` | past: working; live: records arrive, token attributes not yet checked |
| OpenCode | native OTel (AI SDK spans): `experimental.openTelemetry` + `OTEL_EXPORTER_OTLP_ENDPOINT`; sends prompt text | `~/.local/share/opencode/opencode.db` | past: working; live: records arrive, see pitfall |
| Pi | no OTel exporter; extension `pi-telemetry.ts` posts OTLP logs | `~/.pi/agent/sessions/` | past: working; live: extension tested in `pi -p` (records arrive, one per attempt incl. retries) |
| Antigravity CLI (`agy`) | no user-configurable OTel; past logs only | `~/.gemini/antigravity-cli/conversations/` | past: working; live: none |
| Gemini CLI | native OTel: `telemetry` block in `settings.json` | not read yet | to verify |
| GitHub Copilot | no per-call export known; org usage from GitHub Copilot metrics API | | to verify |
| Cursor | no per-call export known; team usage and spend from Cursor admin API | | to verify |
| Long tail: Windsurf, Cline/Roo, Aider, Amp, Kiro | local session logs (`transcripts.md`) or an LLM gateway | | to research |

Three paths, in order of preference:

1. Native OTel from the harness: per call, most detail.
2. LLM gateway (LiteLLM or a cloud AI gateway) between harness and model API: per call, works for any harness that uses an API key; blind to subscription plans.
3. Vendor admin APIs or local session logs: per user and day, or per session after the fact.

Versions checked: Codex CLI 0.162.1, OpenCode 1.19.0, Pi 1.1.0, agy 1.3.5. Below, `<endpoint>` is the collector base URL, e.g. `http://127.0.0.1:6979`.

## Claude Code

Live: env vars in `claude-code-with-telemetry` (one process), or the same keys under `env` in `~/.claude/settings.json` (every session). Undo: remove those keys.

Past: one JSONL per session; assistant entries carry `message.usage` and `message.model`, one entry per content block (deduplicated by `requestId`). Cost is not logged; `schemas/prices.json` estimates it.

## Codex CLI

Live: add to `~/.codex/config.toml`. Undo: delete the block.

```toml
[otel]
environment = "local"
log_user_prompt = false   # keep prompt text out
exporter = { otlp-http = { endpoint = "<endpoint>/v1/logs", protocol = "json" } }
metrics_exporter = { otlp-http = { endpoint = "<endpoint>/v1/metrics", protocol = "json" } }
trace_exporter = { otlp-http = { endpoint = "<endpoint>/v1/traces", protocol = "json" } }
```

For one process only: `codex -c 'otel.exporter={otlp-http={endpoint="<endpoint>/v1/logs",protocol="json"}}' ...` (same keys as `-c` overrides). Events seen locally: `codex.conversation_starts`, `codex.api_request`, `codex.sse_event`, `codex.user_prompt`, `codex.tool_decision`, `codex.tool_result`; the binary also names `codex.turn.token_usage.*` and `codex.turn.cost_microusd`. Unverified: which event carries token counts in practice. Records include `user.email` and `user.account_id`.

Past: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Per model response one `event_msg` of type `token_count` with `last_token_usage` (repeats with an unchanged running total are skipped); `input_tokens` includes `cached_input_tokens` and output includes reasoning. Model from `turn_context`, folder from `session_meta.cwd`, subagent sessions have `session_meta.source.subagent`. Cost is not logged; `schemas/prices.json` prices for `gpt` are guesses.

## OpenCode

Live: in `~/.config/opencode/opencode.json` set `"experimental": {"openTelemetry": true}` and export `OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint>` (optional `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_RESOURCE_ATTRIBUTES`) in the shell that starts `opencode`. Without the env var nothing is sent; without the config flag only OpenCode's own logs and internal spans are sent. Undo: remove the key and the variable. Sends logs as JSON to `/v1/logs` and spans to `/v1/traces`.

Pitfall: the AI SDK spans (`ai.streamText`, `ai.streamText.doStream`) include the full prompt (`ai.prompt`, `ai.prompt.messages`), seen locally. There is no setting to turn that off, so this counts as full transcripts (`transcripts.md`): only with the data owner's consent, or strip those attributes in an OpenTelemetry Collector before storage. Unverified: `ai.usage.*` token attributes on completed spans.

Past: SQLite `~/.local/share/opencode/opencode.db`, opened read-only. `message.data` (JSON) for assistant messages has `modelID`, `cost` (OpenCode's own estimate, used as is), `tokens.input` (uncached), `tokens.output` (without reasoning), `tokens.reasoning`, `tokens.cache.read/write`; tool names from `part` rows of type `tool`; subagent sessions have `session.parent_id`. The script pulls only these fields with `json_extract`.

## Pi

Live: Pi has no OTel exporter (its `pi-telemetry` package defines span contracts without an exporter). Copy `pi-telemetry.ts` to `~/.pi/agent/extensions/`; on every finished model response it posts one OTLP log record (`pi.api_request`: model, provider, tokens incl. reasoning, cost, tool names, folder, session id) to `$OTEL_EXPORTER_OTLP_ENDPOINT/v1/logs`, default `http://127.0.0.1:6979`. Try it for one run without installing: `pi -e pi-telemetry.ts -p ...`. Undo: move the file out of `extensions/`. Tested inside `pi -p` 1.1.0: one record per model attempt, failed attempts arrive with `stop_reason` `error` and zero tokens.

Past: `~/.pi/agent/sessions/--<path>--/<timestamp>_<id>.jsonl` (or `$PI_CODING_AGENT_DIR/sessions`). Assistant `message` entries carry `usage` (`input` uncached, `output`, `cacheRead`, `cacheWrite`, `cost.total` computed by Pi) and `model`; `usage` entries (cache warming) and summaries with `usage` count too. Local models report cost 0.

## Antigravity CLI (`agy`)

Live: none. The binary reads no `OTEL_*` variables; its telemetry goes to Google only (`Enable Telemetry` in `/config`). Hooks exist (`~/.gemini/config/hooks.json`, events such as `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd`, each a `{"type": "command", "command": ...}` entry under a named group), but the hook input is unverified, so there is no per-call path yet. Fallback: run `from-transcripts.py` on a schedule, or from a `SessionEnd` hook, and ship its output.

Past: one SQLite file per conversation in `~/.gemini/antigravity-cli/conversations/<id>.db` (the IDE app writes the same format to `~/.gemini/antigravity/conversations/`), protobuf blobs. Field numbers come from the descriptors embedded in the `agy` binary: in `steps.metadata` (`CortexStepMetadata`) `1` created_at, `4` tool_call (`2` name), `9` model_usage (`ModelUsageStats`: `2` input, `3` output incl. thinking, `4` cache write, `5` cache read); step type `15` is a model response, `14` a user prompt. Model name from `gen_metadata` (`1.19` response_model, mapped to steps by `2` step_indices). Workspace folder from `~/.gemini/antigravity-cli/cache/conversation_metadata.json`. Cost is not logged; `schemas/prices.json` prices for `gemini` are guesses. Unverified: subagent conversations (all counted as main).

## Workflow

1. Detect installed harnesses on the workstation.
2. Pick the path per harness from the table.
3. Write settings to per-user config files, not shell env; corporate rollouts ship them through the harness's managed/enterprise settings.
4. Verify with one short prompt per harness.

## Pitfalls

- Cost in telemetry is a list-price estimate. On flat subscriptions (Max, Team, seats) real spend comes from billing (`../04-auto-analysis/billing.md`).
- Harnesses drop telemetry silently when the endpoint is down.
- Attribute names and local log formats change between harness versions; record the harness version with every record. `from-transcripts.py` skips a harness whose reader fails and says so on stderr.
- Token fields mean different things per harness (input with or without cache, output with or without reasoning); the script normalizes to uncached input and output including reasoning.
- Users can unset env vars; only managed settings make it stick.
- The same person shows up with a different identity per harness (vendor account email, GitHub handle); mapping in `../06-optional/identity.md`.
- Headless runs (CI, scheduled agents) have no human user; tag them as such (`../04-auto-analysis/deployments.md`).
