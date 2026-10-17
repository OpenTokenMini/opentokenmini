# analyze

Placeholder. Joins measured sessions with integrations and turns them into metrics, outliers and recommendations. Method: `METHOD.md`.

- Input: records from `../measure/`, data from `../integrations/`.
- Output: `output.md` (summary and outliers), read by `../dashboard/` and `../mcp-server/`.
- Data it touches: read-only on inputs. Decision models (`decision-models.md`) run where the owner chooses; with a local model, nothing leaves the owner's infrastructure.

## Files

- `METHOD.md` analysis levels and how to read them.
- `output.md` summary and outliers contract.
- `decision-models.md` connector to classification models (optional, owner picks the vendor).
- `quality.md` semi-automated checks of security, performance, usability and other software attributes.
- `recommendations.md` changes to suggest, each with how it was measured; includes harness token configs.
