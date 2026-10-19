# Analysis method

The session is the unit; every integration attaches to sessions by user, time and repo. Placeholder: levels to define.

| Level | Question | Needs |
|---|---|---|
| Session | Where do tokens and time go inside a session? | `../02-measure/` |
| Session vs code | What did the session change, and did it merge? | version control |
| Session vs infra and services | Did it change infra, did services get slower or break? | observability |
| Intent | What was the user trying to do, and what did it cost? | intent labels (`../06-optional/decision-models.md`) |
| Per user | Who gets the most out of agents, and how? | opt-in, see measure privacy defaults |
| Business impact | Which tickets or outcomes did the spend move? | issue trackers |
| MCP effectiveness | Which MCP servers waste calls (outdated docs, errors, loops)? | `../04-auto-analysis/mcp-usage.md` |
| Org visibility | Can agents see the structure they work in (repos, docs, services, owners)? | docs, version control, identity |
| Non-technical users | What did non-engineers produce with agents (docs, processes)? | docs, chat usage exports |

## Decision points

Where a decision model (`../06-optional/decision-models.md`) replaces a judgment call. Each has a fixed question and options; `../06-optional/decide/` runs outlier explanation and recommendation ranking on `analysis.json` (plus commit links for `../04-auto-analysis/impact/`); intent is not implemented. Lead below `MIN_LEAD` over the runner-up = "unsure", left to a person.

| Point | State | Question | Options |
|---|---|---|---|
| Intent | first prompt excerpt or transcript summary (needs transcripts or intent labels, 2.4) | What was the user trying to do? | feature, bug fix, refactor, research, infra or ops, docs, review |
| Outlier explanation | one costly session's metrics vs the period median | What best explains this session's cost? | subagent fan-out, long session, agent loop, heavy context, normal |
| Recommendation ranking | period summary: token mix, subagent share, model mix, top tools | Does this usage data support suggesting this change: X? (yes/no per candidate in `recommendations.md`) | yes, no |

Run: `python3 06-optional/decide/decide.py` from the repo root (usage and config: `../06-optional/decide/AGENTS.md`).
