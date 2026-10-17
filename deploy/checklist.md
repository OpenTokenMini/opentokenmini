# Deployment checklist

One list, read by people and agents. Each item has an id, a section number, a level (`required`, `recommended`, `optional`) and how to check it. The service evaluates the automatic checks and shows the result in `../dashboard/` and through `../mcp-server/` (`checklist()`): done, missing, or worth adding. Placeholder: checks are not implemented.

| Id | Section | Item | Level | Check |
|---|---|---|---|---|
| host | 1.1 | service running, reachable over TLS | required | health endpoint |
| auth | 1.2 | ingest and dashboard behind auth | required | unauthenticated request rejected |
| store | 1.3 | durable storage, retention set | required | store writable, retention configured |
| records | 2.1 | records arriving | required | records in the last hour |
| harness | 2.2 | each harness in use enabled | required | records per harness |
| adoption | 2.5 | share of directory users active | recommended | `../measure/adoption.md` |
| baseline | 2.1 | one week measured before any change | required | first record older than 7 days |
| vcs | 3.1 | version control connected | recommended | last sync time |
| billing | 3.4 | billing connected | recommended | last sync time |
| trackers | 3.3 | issue tracker connected | optional | last sync time |
| obs | 3.5 | observability connected | optional | last sync time |
| decision | 4.3 | decision model reachable | optional | test request |
| mcp | 5.2 | MCP server registered in the orchestrator | optional | last tool call |

Manual items (no automatic check): privacy defaults announced to users, data region decided, undo instructions shared.
