# analyze

Joins measured sessions with integrations and turns them into metrics, outliers and recommendations. Method: `METHOD.md`.

- Input: records from `../02-measure/`, data from `../04-auto-analysis/`.
- Output: `sessions.jsonl`, `analysis.json` and `readout.json` (pipeline: quality, mcp, orchestration, context, deployments and issues sections) in the data dir (contract: `output.md`, `../02-measure/schemas/`), read by `../05-dashboards/` and `../06-optional/mcp-server/`.
- Data it touches: read-only on inputs. The pipeline's local `quality`, `mcp`, `orchestration` and `context` stages read Claude Code transcripts (and MCP config server names) in memory and write only counts (see their AGENTS.md). The pipeline's optional `deployments` and `issues` stages call GitHub through the user's `gh` CLI (read-only metadata); off with `NETWORK = False` in `pipeline.py` or `--no-network`. Decision models (`../06-optional/decision-models.md`) run where the owner chooses; with a local model, nothing leaves the owner's infrastructure.

## Files

- `METHOD.md` analysis levels, how to read them, and decision points.
- `analyze/` events -> sessions, metric catalog, outliers, recommendation candidates.
- `pipeline.py` runs the batch stages in order (normalize, readers, analyze, impact, decide, impact2, quality, mcp, orchestration, context, deployments, issues): `python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run] [--no-network]`. quality, mcp, orchestration, context, deployments and issues are optional: a failure there becomes `{"skipped": reason}` in `readout.json` and the pipeline goes on; a failure in the others stops it. deployments and issues are skipped with a log line (and `{"skipped": reason}` in `readout.json`) when network is off, `gh` is missing or unauthenticated, or there are no repos; they get `--repo` from config `impact.repos`, else from the repos of sessions impact linked (`MAX_REPOS`).
- `tests/` unit tests for this stage.
- `../06-optional/decide/` runs the decision points on `analysis.json` (replaces `decision-points.py`, now in `todelete/`).
- `output.md` summary, outliers and `readout.json` contract.
- `../06-optional/decision-models.md` connector to classification models (optional, owner picks the vendor).
- `../04-auto-analysis/quality.md` semi-automated checks of security, performance, usability and other software attributes.
- `recommendations.md` changes to suggest, each with how it was measured; includes harness token configs.
