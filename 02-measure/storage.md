# Storage

Placeholder. Where records live after the collector receives them.

- Input: raw records from `collector/collector.py`.
- Output: queryable store for `../03-analyze/`.
- Data it touches: everything measured; this is where retention and deletion apply.

## Coverage (tentative)

- First: append-only JSONL per day, queried with DuckDB or SQLite. Zero services, enough for one team.
- Next: Postgres for orgs that already run one.
- Large orgs: ClickHouse, or the existing OTel backend (`../04-auto-analysis/cloud-logs.md`).

## Pitfalls

- Each record repeats user email and ~10 identity attributes: hash or drop on ingest if the owner asks.
- Retention and deletion requests (GDPR) must work per user.
- Raw records stay unmodified; derived tables are rebuilt from them, never edited in place.
- Data residency: the store's region is the owner's choice, stated at deploy.
