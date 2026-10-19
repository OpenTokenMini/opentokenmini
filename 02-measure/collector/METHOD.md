# collector method

Each rule has an ID cited in the code. Constants are at the top of collector.py / normalize.py.

## Receiver (collector.py)

- **N-body-limit**: request body over `MAX_BODY` bytes -> 413. Applied again to the decompressed size of gzip/deflate bodies (bomb guard).
- **N-pb**: protobuf bodies are decoded with `opentelemetry-proto` if importable (optional, not stdlib), else logs/traces with protowire.py (stdlib wire decoder, metrics not covered). Malformed protobuf -> 400.
- **N-undecoded**: a body that is neither decodable JSON nor protobuf is dropped; the record keeps `undecoded: {bytes, sha256, content_type, reason}` (reason `not_json_object` or `no_protobuf_decoder`). `KEEP_RAW_UNDECODED = True` stores the body as `data_b64` instead, NOT redacted. One warning per process. normalize.py reads neither.
- **N-redact**: any OTLP attribute (any depth) whose key matches `REDACT` gets value `"[redacted len=N]"`, N = `len(json.dumps(original AnyValue))`. Example: `prompt="hello"` -> `[redacted len=24]`.
- **N-identity**: when `collector.hash_identity` is true, string values of keys in `IDENTITY` become `sha256(OTM_ID_SALT + value).hexdigest()[:HASH_LEN]`; values already matching 12 lowercase hex chars are kept. Example: `a@b.c` -> `d648b243a3e8`. `OTM_ID_SALT` unset = empty salt (plain sha256); normalize.py must see the same value.
- **N-pii**: always on, at write time, in every string of the decoded body: values of `PII_KEYS` (`user.email`, `user.account_uuid`) become `hash_id(value)`, every `EMAIL` match inside any string becomes `hash_id(match)`, and `/home/<user>` becomes `~`. Example: `cwd=/home/u/p` -> `~/p`; body `by a@b.c` -> `by d648b243a3e8`. Known false positive: strings like `icon@2x.png` match `EMAIL`.
- **N-raw-file** (`files` sink): one line per request in `<data>/otel/<signal>-<YYYY-MM-DD>.jsonl`, day = UTC date of `recv_ts`. Older files from the first collector are named by local day.

## Normalizer (normalize.py)

- **N-raw-read**: reads v1 and legacy raw lines whose `data` is an object; unparsable, `undecoded` or `data_b64`-only lines are counted in `skipped_raw`.
- **N-signals**: only logs and traces; metrics repeat the log events.
- **N-harness**: `service.name` `claude-code` -> claude-code, prefix `codex` -> codex (`codex_exec` too), `opencode`, `pi`; anything else skipped.
- **N-user**: first of `USER_KEYS` present, hashed as N-identity (already hashed kept).
- **N-project**: OTel carries no cwd for claude-code/codex -> `UNKNOWN_PROJECT`; pi uses basename of `cwd`; opencode uses header `x-opencode-project`.
- **N-claude**: `api_request` -> api_call with disjoint tokens (input, output, cache_read, cache_creation), cost = `cost_usd` as `reported_total_allocated`; `api_error` -> api_call with error, retries = attempt - 1; `subagent` = `query_source` starts with `agent:`. Cache writes split by TTL when the event carries `cache_creation_5m_tokens` / `cache_creation_1h_tokens` (C-cache-ttl).
- **N-claude-agent**: `query_source` and `agent.name` are kept as optional nullable `query_source`, `agent_name` on Claude api_call events (per-subagent-type breakdowns: `agent:builtin:<type>`, `compact`, `generate_session_title`, `repl_main_thread`). `user_prompt`, `tool_decision` mapped by name. Events without `session.id` dropped.
- **N-codex**: `codex.sse_event` with `input_token_count` -> api_call; input includes cached, output includes reasoning (subtracted by `make_tokens`). Example: input 1000, cached 800, output 50, reasoning 30 -> input 200, cache_read 800, output 20, reasoning 30. sse_event with `error.message` -> errored api_call.
- **N-pi**: `pi.api_request` log records from the pi-telemetry extension; tokens disjoint; `cost_usd` is the reported total; `stop_reason` error/aborted -> error.
- **N-opencode**: spans named in `OPENCODE_SPANS`; `ai.usage.*` inclusive like N-codex; status code 2 -> error; duration = end - start. Success spans of short runs may never flush before the process exits.
- **N-decision**: decision values in `ACCEPT` -> accept, `REJECT` -> reject.
- **N-claude-ttl**: applies only when the 5m/1h keys are absent (older Claude Code). Then OTel `cache_creation_tokens` has no 5m/1h split and `cost_usd` prices it below the 1h rate (req_011CgA3u: otel $0.0570 vs transcript $0.0705, all 1h). Calls with cache writes get `cache_split: "unknown"` and cost = max(cost_usd, list price with every cache write at the 1h rate, basis `list_price`). Tier 1h because it is the upper bound: OTel-only cost can over-state, never under-state. analyze M-dedup-ttl replaces it with the transcript split when the call is in both sources.
- **N-codex-prewarm**: `codex.sse_event` response.completed with `output_token_count` 0 and no `ttft_ms` is the startup websocket warmup (same ms as `codex.startup_phase` `startup_prewarm_websocket_warmup`); rollouts do not count it, so it is dropped.
- **N-opencode-id**: `request_id` is null: `x-opencode-request` is the user message id, shared by every retry/step of that turn and never equal to the transcript's assistant message id, so it cannot dedup (ses_eb0268: 6 retried spans collapsed to 1 and the transcript call was kept, 2 total). With null ids analyze rule 3 keeps the 6 OTel calls and drops the transcript one in the window.
- **N-dedup**: successful api_call keyed by (harness, kind, request_id); everything else by its full JSON. First seen wins; output sorted by (ts, harness, session_id).
