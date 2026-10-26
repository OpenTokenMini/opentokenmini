# Issue trackers

Links sessions to tickets, for intent and business impact. Working: GitHub Issues and PRs via `gh` in [`issues/`](issues/AGENTS.md) (joins PRs to sessions through `impact/`'s linked commits). Jira and Linear: placeholder.

- Reads: ticket key, type, status, timestamps, assignee, labels, linked branches or PRs. Description only if the owner enables it.

## Coverage (tentative priority)

- First: Jira (Cloud and Data Center), GitHub Issues, Linear.
- Next: Azure Boards, GitLab Issues.
- Long tail: Asana, ClickUp, Shortcut, YouTrack. Generic path: ticket keys parsed from branch names and PR titles, no API.

## Workflow

1. Owner names projects and the ticket key convention.
2. Link ticket to change through PR links or keys in branch/PR title; change to sessions through `git.md`.
3. Report spend per ticket type (bug, feature, chore) and per epic.

## Pitfalls

- Key conventions are inconsistent; measure the share of changes with no ticket and report it.
- Story points are not comparable across teams; do not use them as impact.
- Tickets closed without code, or code without tickets: both are signal, not noise.
