# analyze

Joins measured sessions with integrations and turns them into metrics, outliers and recommendations. Method: `METHOD.md`.

- Input: records from `../02-measure/`, data from `../04-auto-analysis/`.
- Output: `sessions.jsonl` and `analysis.json` in the data dir (contract: `output.md`, `../02-measure/schemas/`), read by `../05-dashboards/` and `../06-optional/mcp-server/`.
- Data it touches: read-only on inputs. Decision models (`../06-optional/decision-models.md`) run where the owner chooses; with a local model, nothing leaves the owner's infrastructure.

## Files

- `METHOD.md` analysis levels, how to read them, and decision points.
- `analyze/` events -> sessions, metric catalog, outliers, recommendation candidates.
- `pipeline.py` runs the batch stages in order (normalize, readers, analyze, impact, decide, impact2): `python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run]`.
- `tests/` unit tests for this stage.
- `../06-optional/decide/` runs the decision points on `analysis.json` (replaces `decision-points.py`, now in `todelete/`).
- `output.md` summary and outliers contract.
- `../06-optional/decision-models.md` connector to classification models (optional, owner picks the vendor).
- `../04-auto-analysis/quality.md` semi-automated checks of security, performance, usability and other software attributes.
- `recommendations.md` changes to suggest, each with how it was measured; includes harness token configs.
