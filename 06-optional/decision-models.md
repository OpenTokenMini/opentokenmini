# Decision models (optional)

Small models that pick among listed options and return a probability per option: cheap and fast enough to run on every event, without spending LLM tokens. Optional, but they power intent labels, outlier explanations, quality checks and recommendation ranking. The owner picks the vendor, or a local model.

## Method

- Decision model when the answer is one of a set the code can list: pick, filter, route, rank, judge (yes/no over an output). One question per item, one probability per option.
- LLM only to write text that did not exist (a report, a suggested config). Options not listable: the LLM proposes candidates, the decision model picks.
- The distribution is the signal. Peaked: act on the top option. Flat or a small lead over the runner-up: report "unsure" and leave it to a person. Thresholds are named constants in the caller, not in the connector.
- Calibrate by editing the options' rubrics and thresholds; debug by reading the distribution.
- State is metadata or a short excerpt; prompts and code go in only if the measure level includes them (`../02-measure/METHOD.md`).

## Connector

`decide/` (`decide/AGENTS.md`): vendors are functions in `decide/connectors.py` (`VENDORS`), picked by `decide.vendor` in `01-deploy/config.json`. One call from the CLI: `python3 06-optional/decide/decide.py --ask "state" "question" [option ...]` (no options = yes/no).

## Vendors

### jev (implemented)

Hosted decision model by TypeSafe. One question per call here; the API also takes N questions per request in parallel (32k tokens shared by state and questions), worth using for filters over many items.

- Env: `TYPESAFE_API_KEY`, optional `JEV_URL`.
- Data: the state leaves the owner's infrastructure; send aggregates or redacted excerpts unless the owner agreed.

### d1 (drafted, local, untested)

LiquidAI decision model run by the owner (~3B parameters, one GPU). Same question types as jev; nothing leaves the owner's machine.

- Config: `decide.vendor: "d1"`, env `D1_URL` of a small server the owner runs (no reference server here yet) exposing `POST /ask {state, q, type, opts: [[name, rubric], ...]}` and answering `{answer}` in jev shape.

### Cloudflare clef, LLM fallback

Placeholder. LLM fallback: ask for one option name and read token logprobs, or sample a few times and count; slower and costlier, only when no decision model is available.

## Where it plugs in

- `../03-analyze/METHOD.md` decision points: intent, outlier explanation, recommendation ranking.
- `../04-auto-analysis/quality.md` per-event checks.
- `../02-measure/` optionally at ingest, to label events as they arrive.
