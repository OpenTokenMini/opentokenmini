# Measurement method

What to measure and why, independent of any implementation. Placeholder: outline only.

## Levels (owner picks per deployment)

1. Telemetry only (default): per API call cost, tokens, latency, errors, retries, tool decisions. No prompts, no code.
2. Telemetry + intent labels: prompts classified locally into an intent (bugfix, feature, refactor, docs, exploration); only the label leaves the machine.
3. Full transcripts: complete session logs pushed to the collector. For small orgs or orgs that want everything; explicit opt-in.

## Baseline

- At least one week measured before any change.
- Same metrics and same period length after the change.
- Record anything else that changed in the period (team size, kind of work, pricing).

## Units

- Per call, per session, per user, per team, per repo.
- Spend per merged change (needs `../04-auto-analysis/git.md`).

## Privacy defaults

- Aggregated per team by default. Per-person metrics are opt-in and visible to that person.
- Nothing retroactive: data exists only from activation.
