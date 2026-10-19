# schemas

The contracts between stages and the only shared code. Stages never import each other; they import from here after finding the repo and putting `02-measure/` on `sys.path`:

```python
REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "02-measure" / "schemas").is_dir())
sys.path.insert(0, str(REPO / "02-measure"))
from schemas.cost import load_prices, make_tokens, event_cost, worst_basis, zero_tokens, zero_cost
from schemas.config import load_config, data_dir, connector
from schemas.check import validate, check_file
```

Exact cost and validation rules: `METHOD.md` (C-*, S-*). Data touched: none; reads only files passed to it.

## Files

| file | contract |
|---|---|
| `raw.schema.json` | collector output `otel/<logs\|metrics\|traces>-YYYY-MM-DD.jsonl`; also accepts the legacy `{ts, signal, service, data}` lines |
| `event.schema.json` | `events/otel.jsonl`, `events/transcript.jsonl` |
| `session.schema.json` | `sessions.jsonl` |
| `analysis.schema.json` | `analysis.json`, `analysis.decided.json` |
| `impact.schema.json`, `impact_summary.schema.json` | `impact.jsonl`, `impact_summary.json` |
| `decision.schema.json` | `decisions.jsonl` |
| `common.schema.json` | shared defs: harness ids, `tokens{5}`, `cost{5}`, cost_basis, ts |
| `prices.json` | USD per million tokens by model substring (C-price-match) |

All records carry `v: 1`. Changing a schema means bumping `v` and noting it for every stage that reads it. Timestamps are ISO 8601 UTC. Harness ids: `claude-code codex antigravity opencode pi`.

## Check a file

```
python3 02-measure/schemas/check.py ~/.local/share/opentokenmini/events/otel.jsonl     # schema inferred from the name
python3 02-measure/schemas/check.py out/x.jsonl session                                 # or given
```

Exit 0 when valid; otherwise one error per line (`line N: $.cost: C-sum ...`), exit 1. Checks types, required keys, enums, no extra keys on records, and the semantic rules C-sum, S-event-kind, S-decision-choice, S-session-order.

## Config

Root `01-deploy/config.json` (gitignored; copy `01-deploy/config.example.json`). Keys are stage dir names; `null` means the constant at the top of that stage's file; keys starting with `_` are comments at any depth. Unknown keys, wrong value types (checked against `DEFAULTS`; null-default keys per `NULLABLE`) and unknown harness ids in `readers.enabled`/`readers.paths` raise ValueError. Missing file = all defaults (`DEFAULTS` in `config.py`).

- `load_config(path=None)`: `--config PATH` > `$OTM_CONFIG` > `<repo>/01-deploy/config.json` > defaults, deep-merged (`readers.paths` replaced as a whole).
- `data_dir(cfg)`: `$OTM_DATA_DIR` > `data_dir` > `~/.local/share/opentokenmini`. Refuses a dir inside the repo.
- `connector(registry, name, key)`: picks a connector function from a stage's name → function dict, with an error listing the available names.

## Reconfigure

Add a price: insert a key in `prices.json` above any shorter key it contains (`"gpt-6": {...}` before `"gpt"`). Add a harness: append its id to the `harness` enum in `common.schema.json` and to `HARNESSES` in `config.py`, bump `v`.

## Adapt, trade-offs, decisions for the human

- Adapt: prices in `prices.json` to your contracts and models; add harness ids as above. Keep schemas stable; downstream stages and external consumers read them.
- Trade-offs: one shared validator, stdlib only (a subset of JSON Schema, not a full implementation). Costs not reported by the harness are estimated from `prices.json`; `cost_basis` on each record says which. Price rows may note their own source (`basis`: fitted, guess), which cost code ignores.
- Decisions for the human: whether estimated prices are close enough to report, or whether billing data (`04-auto-analysis/billing.md`) should replace them; when to bump `v`.
