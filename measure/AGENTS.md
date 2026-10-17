# measure

Collects what coding agents do: a collector service, and telemetry turned on in each harness on each workstation. Method: `METHOD.md`.

- Input: OTLP over HTTP/JSON from harnesses; optionally full session transcripts (`transcripts.md`).
- Output: raw records, one JSON line per request (`/tmp/claude-otel.jsonl` today), each `{ts, path, data}`.
- Data it touches: whatever the harnesses send. Default: no prompts, no code. Nothing is filtered or added.

## Files

- `collector.py` receives OTLP and appends it unmodified. `python3 collector.py`, listens on `127.0.0.1:7811`, settings as constants at the top, stdlib only. Still embeds the first dashboard (`GET /`, `GET /data`, `POST /console` for its browser errors).
- `from-transcripts.py` summarizes local Claude Code session logs (last N days) into usage JSON for `../docs/demo/`. Reads usage metadata only, never prompts or code.
- `claude-code-with-telemetry` runs `claude` with telemetry on for that process only.
- `harnesses.md` how to turn telemetry on in each harness.
- `transcripts.md` opt-in push of full session transcripts (placeholder).
- `storage.md` where records live, retention (placeholder).
- `adoption.md` who has telemetry on vs everyone who should (placeholder).

## Install: service (whoever owns the data)

1. Ask where it runs: this machine, a cloud VM/container (`../deploy/`), or an existing OTLP backend (Datadog, Grafana, OpenTelemetry Collector).
2. Run `collector.py` there, or configure the existing backend to accept OTLP HTTP/JSON.
3. Choose ingest auth: none (local trial), shared token, or corporate login (`../integrations/identity.md`).
4. Verify: send a test OTLP record and confirm it is stored.
5. Hand over to workstations: endpoint URL, auth, harnesses to enable.

Never change anything outside the chosen host without asking.

## Install: each workstation or agent instance

Needs the endpoint URL and auth from the service step.

1. Detect installed harnesses.
2. For each, apply the matching entry in `harnesses.md`, preferring per-user settings files over shell env.
3. Optionally enable git metadata for repos the user names (`../integrations/version-control.md`).
4. Optionally apply token configs (`../analyze/recommendations.md`); ask first, they change agent behavior.
5. Verify: one short prompt per harness, records arrive at the endpoint.
6. Report what changed and how to undo it.

Show the user every file before modifying it. Never send prompt or code content unless the owner enabled it explicitly.

## To do

- per-day files and a durable store instead of `/tmp`
- drop or hash repeated identity attributes (email) on ingest
- move the embedded dashboard to `../dashboard/`
