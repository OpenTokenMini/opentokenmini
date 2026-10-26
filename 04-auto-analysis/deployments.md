# CI

Pipeline results for agent-made changes, and agents that run headless in CI. GitHub Actions works: `deployments/` (reads runs with `gh`, joins them to sessions through `impact.jsonl`); the rest is placeholder.

- Reads: pipeline status per commit or PR, duration, failed step. Agent runs in CI emit telemetry like workstations, tagged as headless.

## Coverage (tentative priority)

- First: GitHub Actions (working, `deployments/`), GitLab CI (placeholder connector).
- Next: Jenkins, CircleCI, Buildkite, Azure Pipelines.

## Pitfalls

- Flaky tests make failure rate noisy; compare against the repo's baseline failure rate.
- A run tests only its head commit; in a multi-commit push only the tip's session is credited.
- CI agent runs bill to an org key, not a person; attribute to the triggering PR.
