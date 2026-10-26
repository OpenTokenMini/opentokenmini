# Adoption inventory

Placeholder. Who has telemetry on, compared with everyone who should. Transparent to the operator and to their agent: the same numbers in `../05-dashboards/` and `../06-optional/mcp-server/`.

- Input: user directory (`../06-optional/identity.md`, or a CSV), records arriving at the collector, managed-settings rollout state if the harness vendor exposes it.
- Output: per user: harnesses seen, last record time, measure level, how it was enabled (managed corporate rollout or self-install). Per group (team, area, any directory attribute): share of users active, per harness.
- Data it touches: identity and last-seen timestamps only.

## The delta

- Directory users with no records: not enabled, or enabled and broken.
- Records from users not in the directory: personal accounts, contractors, aliases to map.
- Users whose records stopped: endpoint unreachable, settings removed, harness updated.

## Pitfalls

- A user with no agent usage looks the same as a user with telemetry off. Pair with seats from `../04-auto-analysis/billing.md` to tell them apart.
- "Active" needs a window (e.g. a record in the last 7 days), as a named constant.
