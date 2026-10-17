# Harness telemetry

How to get per-call usage out of each coding agent (harness) into the collector. Nothing else about the harness changes.

## Coverage (tentative priority, not measured market share)

| Harness | Path | Status |
|---|---|---|
| Claude Code | native OTel: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_*`; see `claude-code-with-telemetry` | working |
| Codex CLI | native OTel: `[otel]` in `~/.codex/config.toml` | to verify |
| Gemini CLI | native OTel: `telemetry` block in `settings.json` | to verify |
| GitHub Copilot | no per-call export known; org usage from GitHub Copilot metrics API | to verify |
| Cursor | no per-call export known; team usage and spend from Cursor admin API | to verify |
| Long tail: Windsurf, Cline/Roo, Aider, OpenCode, Amp, Kiro, Antigravity, Pi | local session logs (`transcripts.md`) or an LLM gateway | to research |

Three paths, in order of preference:

1. Native OTel from the harness: per call, most detail.
2. LLM gateway (LiteLLM or a cloud AI gateway) between harness and model API: per call, works for any harness that uses an API key; blind to subscription plans.
3. Vendor admin APIs or local session logs: per user and day, or per session after the fact.

## Workflow

1. Detect installed harnesses on the workstation.
2. Pick the path per harness from the table.
3. Write settings to per-user config files, not shell env; corporate rollouts ship them through the harness's managed/enterprise settings.
4. Verify with one short prompt per harness.

## Pitfalls

- Cost in telemetry is a list-price estimate. On flat subscriptions (Max, Team, seats) real spend comes from billing (`../integrations/billing.md`).
- Harnesses drop telemetry silently when the endpoint is down.
- Attribute names change between harness versions; record the harness version with every record.
- Users can unset env vars; only managed settings make it stick.
- The same person shows up with a different identity per harness (vendor account email, GitHub handle); mapping in `../integrations/identity.md`.
- Headless runs (CI, scheduled agents) have no human user; tag them as such (`../integrations/ci.md`).
