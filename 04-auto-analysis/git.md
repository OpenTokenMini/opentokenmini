# Version control

Placeholder. Links spend to commits and merged changes: the base for spend per merged change.

- Reads: author, timestamps, `Co-Authored-By` trailers, branch, changed file paths and line counts, PR/MR id, review state, merge status. Never code unless the owner enables diffs.

## Coverage (tentative priority)

- First: GitHub (cloud and Enterprise Server), GitLab (SaaS and self-managed).
- Next: Bitbucket (Cloud and Data Center), Azure DevOps Repos.
- Long tail: Gitea/Forgejo, Gerrit, Perforce. Any git host works through local `git log` on repos the user names, without PR data.

## Workflow

1. Owner names the orgs or repos.
2. Read-only credentials: GitHub App or GitLab group token with metadata scope, not personal tokens.
3. Link session to change: repo path from telemetry, author identity, time window, agent trailer, branch.
4. Link change to outcome: merged, reverted, time to merge, review rounds.

## Pitfalls

- Squash and rebase merges rewrite SHAs: link through the PR/MR, not commits.
- Agent trailers can be turned off; time window plus author is the fallback, and it is fuzzy.
- Bot and service-account commits must be excluded.
- Monorepos: attribute by changed path, not by repo.
- API rate limits on large orgs: incremental sync, webhooks over polling.
- Reverts and follow-up fixes are the cost of a bad change; count them against the original.
