# CI

Placeholder. Pipeline results for agent-made changes, and agents that run headless in CI.

- Reads: pipeline status per commit or PR, duration, failed step. Agent runs in CI emit telemetry like workstations, tagged as headless.

## Coverage (tentative priority)

- First: GitHub Actions, GitLab CI.
- Next: Jenkins, CircleCI, Buildkite, Azure Pipelines.

## Pitfalls

- Flaky tests make failure rate noisy; compare against the repo's baseline failure rate.
- CI agent runs bill to an org key, not a person; attribute to the triggering PR.
