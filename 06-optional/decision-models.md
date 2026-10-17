# Decision models (optional)

Small classification models that pick among listed options: cheap and fast enough to run on every event, without spending LLM tokens. Optional, but they power intent labels, quality checks and anomaly flags. The owner picks the vendor, or a custom model.

## Contract

- Input: `{state, question, options}`; state is the event or session excerpt.
- Output: one probability per option.
- Runs in the owner's infrastructure when the model is local; only the label is stored.

## Vendors

Placeholder, one section each when implemented: d1 (LiquidAI, local), jev, Cloudflare clef, any LLM as fallback.

## Where it plugs in

- `../03-analyze/METHOD.md` intent labels, per-session classification.
- `../04-auto-analysis/quality.md` per-event checks.
- `../02-measure/` optionally at ingest, to label events as they arrive.
