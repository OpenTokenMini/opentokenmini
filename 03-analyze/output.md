# Analysis output

Placeholder. The one output of `analyze/`, read by both `../05-dashboards/` (people) and `../06-optional/mcp-server/` (agents). Same numbers in both.

## Summary

- Configurable per deployment: which metrics (from `../05-dashboards/metrics.md`), period, grouping (team, repo, model, harness, intent).
- Each value carries its definition, period, sample size and the session ids behind it.

## Outliers

- Per metric and group, compared against that group's own baseline (robust z-score or percentile; thresholds as named constants).
- Each outlier: metric, group, value, baseline, sample size, top contributing sessions.
- Examples: a session 10x the team's median spend, an MCP server whose error rate jumped, a repo where spend per merged change doubled.

## Adoption and checklist

- Adoption inventory (`../02-measure/adoption.md`) and deployment checklist state (`../01-deploy/checklist.md`) are part of the output, so operator and agent see the same thing.

## Pitfalls

- Small groups give noisy baselines: below a minimum sample size, report but do not flag.
- Weekly cycles and holidays: compare like with like.
- Per-person outliers follow the privacy defaults in `../02-measure/METHOD.md`.
