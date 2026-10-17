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
