# readers

Reads each harness's local transcripts and writes `events` (source `transcript`) to `<data dir>/events/transcript.jsonl`. Rules and worked examples: METHOD.md (R-* IDs).

## Run

    python3 02-measure/readers/readers.py                       # last 30 days, harnesses from config readers.enabled
    python3 02-measure/readers/readers.py --days 7 --harness codex --harness pi   # only these; other harnesses' lines kept
    python3 02-measure/readers/readers.py --config my.json --out /tmp/otm         # other config / data root

stdout: `{"out", "since", "harnesses": {id: {events, calls, cost, unpriced_calls, error}}}`. A non-null `error` means that reader failed or (antigravity) skipped dbs; the rest still ran.
Tests: `python3 -m unittest discover -s 02-measure/tests -p test_readers.py`. Check output: `python3 02-measure/schemas/check.py <file> event`.

## Reconfigure

- `01-deploy/config.json` -> `readers.enabled`: list of harness ids to read; `readers.paths.<id>`: replace the default root (dir, or the db file for opencode).
- Registry: `READERS` in readers.py, harness id -> `read(since: datetime, cfg) -> Iterable[event]`. Ids must be in `schemas.config.HARNESSES`.
- Default roots and tunables are constants at the top of each `<harness>.py`; `DAYS` in readers.py, `SCRATCH_DIRS` in common.py.

Adding a harness `foo`:
1. Ask the schemas owner to add `foo` to HARNESSES (and prices for its models).
2. `readers/foo.py` with `ROOT = "~/.foo/sessions"` and `def read(since, cfg)` that yields `common.event("api_call", ts, "foo", sid, cwd=..., model=..., tokens=make_tokens(...))` per call (and `"user_prompt"` per human turn, no text). Use `common.root(cfg, "foo", ROOT)`, `common.recent`, `common.ts_ok`.
3. `import foo` and add `"foo": foo.read` to READERS; add a fixture under 02-measure/tests/fixtures/readers/foo/ and a test.

Pitfalls: never copy prompt/tool text into events; tests set `common.HOME = "/home/user"` before building events; modules are imported by name from readers/ (no connectors.py here), so don't add a module whose name matches another stage's.

## Adapt, trade-offs, decisions for the human

- Adapt: `readers.enabled` and `readers.paths` to the harnesses and log locations on this machine; add a reader per new harness.
- Trade-offs: reads past usage with no setup, but local log formats are undocumented and change between harness versions (antigravity field numbers come from binary descriptors). Costs are estimated from `schemas/prices.json`, not billed amounts. Transcript `agent_type` and OTel `agent_name`/`query_source` are separate fields, not unified yet.
- Decisions for the human: which harnesses' logs may be read; whether transcript or OTel data wins when both exist (`analyze.prefer_source`).
