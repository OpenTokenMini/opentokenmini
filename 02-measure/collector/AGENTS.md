# collector

OTLP/HTTP receiver plus normalizer. `collector.py` takes `POST /v1/logs|metrics|traces` (JSON or protobuf, optional gzip), redacts content, hashes identity and writes one `raw` record per request. `normalize.py` turns raw logs/traces into `events` (source `otel`) at `<data dir>/events/otel.jsonl`. Rules and worked examples: METHOD.md (N-* IDs).

    harness --OTLP--> collector.py --sink--> <data>/otel/<signal>-<UTC day>.jsonl --normalize.py--> <data>/events/otel.jsonl

## Run

    python3 02-measure/collector/collector.py                         # 127.0.0.1:6979 (OTM_PORT or config collector.port)
    OTM_PORT=7861 python3 02-measure/collector/collector.py --out /tmp/otm   # scratch instance, other data root
    python3 02-measure/collector/normalize.py --days 7 --harness codex       # --in RAW_DIR, --out EVENTS_DIR
    curl 127.0.0.1:6979/health                              # status ok|stale|degraded, counts per harness, rejects, sink size, disk (N-health)
    python3 02-measure/coverage.py [hours]                  # % of Claude Code requests (transcripts) missing from telemetry (N-coverage)

Persistent user service (Linux; macOS: a LaunchAgent with the same command). The repo path must be a clone that stays, not `/tmp`. Write `~/.config/systemd/user/opentokenmini-collector.service`, then `systemctl --user daemon-reload && systemctl --user enable --now opentokenmini-collector`; `loginctl enable-linger $USER` keeps it running while logged out (ask first). Undo: `systemctl --user disable --now opentokenmini-collector` and move the file out.

    [Service]
    ExecStart=/usr/bin/python3 /ABS/PATH/TO/opentokenmini/02-measure/collector/collector.py
    Restart=on-failure
    [Install]
    WantedBy=default.target

Verify without a harness: `curl -s -XPOST 127.0.0.1:6979/v1/logs -H 'Content-Type: application/json' -d '{"resourceLogs":[{"scopeLogs":[{"logRecords":[{"body":{"stringValue":"otm.test"}}]}]}]}'` answers `{}` and adds a line to `<data>/otel/logs-<UTC day>.jsonl`.

Point a harness at it with `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:6979`. Responses: 200 `{}`, 400 bad body, 401 missing bearer, 413 over MAX_BODY, 500 sink error.
Tests: `python3 -m unittest discover -s 02-measure/tests -p test_collector.py`. Check output: `python3 02-measure/schemas/check.py <file> raw|event`.

## Reconfigure

`01-deploy/config.json` -> `collector`: `sink` (connector name), `bind`, `port` (null = OTM_PORT or 6979), `token_env` (env var holding a bearer token; null = no auth), `hash_identity` (bool).
Registry: `SINKS` in connectors.py, name -> `write(record: dict, cfg: dict) -> None`; raise to answer 500. Existing: `files` (default), `stdout`, `forward_otlp` (re-sends redacted OTLP JSON to `$OTM_FORWARD_URL`).

Worked example, print records instead of writing files: set `"collector": {"sink": "stdout"}` and run `python3 02-measure/collector/collector.py > raw.jsonl`. Adding a sink `foo`: write `def foo(record, cfg)` in connectors.py and add `"foo": foo` to SINKS.

Pitfalls: every stage has a `connectors.py`; collector.py loads its siblings by file path (`_load`), so do the same in tests. Bodies that cannot be decoded are dropped and summarized as `undecoded` (N-undecoded); `KEEP_RAW_UNDECODED` opts into unredacted `data_b64`. Claude Code's `~/.claude/settings.json` env overrides process env, so a per-run `OTEL_EXPORTER_OTLP_ENDPOINT` is ignored when the settings set one.

## Adapt, trade-offs, decisions for the human

- Adapt: bind address, port, auth (`token_env`) and sink to where the data should live (`01-deploy/`); a `forward_otlp` sink or an existing OTel backend can replace the file store.
- Trade-offs: stdlib only, a single process, files per UTC day. Simple to read and move, but no retention, rotation or HA. Redaction and identity hashing happen at ingest, so raw content is never stored and cannot be recovered later.
- Decisions for the human: where it runs and who can reach it; whether to hash identity (`hash_identity`); whether to keep undecodable bodies (`KEEP_RAW_UNDECODED`, unredacted).
