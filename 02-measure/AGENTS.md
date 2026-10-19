# measure

Collects what coding agents do: a collector service, and telemetry turned on in each harness on each workstation. Method: `METHOD.md`.

- Input: OTLP over HTTP/JSON from harnesses; optionally full session transcripts (`transcripts.md`).
- Output: in the data dir (`$OTM_DATA_DIR`, default `~/.local/share/opentokenmini`): raw OTel records `otel/<signal>-<UTC day>.jsonl`, and normalized events `events/otel.jsonl` and `events/transcript.jsonl`. Shapes: `schemas/`.
- Data it touches: whatever the harnesses send. Default: no prompts, no code. Nothing is filtered or added.

## Files

- `collector/` OTLP/HTTP receiver (`127.0.0.1:6979`) and normalizer (raw -> events). Replaces the old `collector.py` (in `todelete/`); the dashboard is no longer embedded (`../05-dashboards/standalone/`).
- `readers/` one reader per harness (Claude Code, Codex, Antigravity, OpenCode, Pi): local session logs -> events. Usage metadata only, never prompts or code.
- `schemas/` JSON schemas for every stage's output, `prices.json`, shared `config.py`, `check.py` validator.
- `from-transcripts.py` thin wrapper over `readers/`: last N days of local logs -> usage JSON for `../00-docs/demo/`. `python3 02-measure/from-transcripts.py 30 > usage.json`.
- `tests/` unit tests for this stage; `tests/fixtures/` also used by later stages.
- `pi-telemetry.ts` Pi extension that sends OTLP log records (Pi has no exporter).
- `claude-code-with-telemetry` runs `claude` with telemetry on for that process only.
- `harnesses.md` how to turn telemetry on in each harness.
- `transcripts.md` opt-in push of full session transcripts (placeholder).
- `storage.md` where records live, retention (placeholder).
- `adoption.md` who has telemetry on vs everyone who should (placeholder).

## Install: service (whoever owns the data)

1. Ask where it runs: this machine, a cloud VM/container (`../01-deploy/`), or an existing OTLP backend (Datadog, Grafana, OpenTelemetry Collector).
2. Run `collector/collector.py` there, or configure the existing backend to accept OTLP HTTP/JSON.
3. Choose ingest auth: none (local trial), shared token, or corporate login (`../06-optional/identity.md`).
4. Verify: send a test OTLP record and confirm it is stored.
5. Hand over to workstations: endpoint URL, auth, harnesses to enable.

Never change anything outside the chosen host without asking.

## Install: each workstation or agent instance

Needs the endpoint URL and auth from the service step.

1. Detect installed harnesses.
2. For each, apply the matching entry in `harnesses.md`, preferring per-user settings files over shell env.
3. Optionally enable git metadata for repos the user names (`../04-auto-analysis/git.md`).
4. Optionally apply token configs (`../03-analyze/recommendations.md`); ask first, they change agent behavior.
5. Verify: one short prompt per harness, records arrive at the endpoint.
6. Report what changed and how to undo it.

Show the user every file before modifying it. Never send prompt or code content unless the owner enabled it explicitly.
