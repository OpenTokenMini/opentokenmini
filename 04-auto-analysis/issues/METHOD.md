# issues: specs

Constants at the top of `issues.py`: `DAYS=30`, `PAGE=50`, `MAX_PAGES=20`, `PR_COMMITS=100`, `TYPE_LABELS`, `KEY_RX`, `REF_RX`, `BRANCH_RX`.

## I-repo: which repos
Each `--repo` is resolved with `realpath`; `repo_label = basename` (same as impact L-repo, so labels join). The GitHub slug comes from `git remote get-url origin` (ssh or https, `.git` optional). No GitHub origin, or `gh` fails for that repo (deleted, renamed, no access): a line on stderr, repo skipped, `repos_scanned` not incremented.

## I-fetch: reading GitHub
`gh api graphql`, `pullRequests` and `issues` (GitHub's `issues` excludes PRs) ordered by `UPDATED_AT DESC`, `PAGE` nodes per page. Kept: nodes with `updatedAt` ≥ now − `--days`. Paging stops at the first page holding an older node, at the last page, or after `MAX_PAGES`; in the last case `"<repo_label>:<kind>"` is added to the summary's `truncated`. Per PR at most `PR_COMMITS` commits and 20 labels and closing issues are read.

## I-keys: ticket keys without an API
From PR title and head branch: `KEY_RX` (`ABC-123`, Jira/Linear) → `keys`; `#N` in the title (`REF_RX`) and a leading number in a branch segment (`BRANCH_RX`: `fix/12-x`, `12-x`, `gh-12_x`) → issue numbers. Numbers count only if that issue is among the fetched issues of the repo (branch digits are often not issues). Title and branch are not stored.

## I-pr: PR record
`state` = `merged` if `mergedAt`, else `open`/`closed`. `issues` = sorted union of GitHub `closingIssuesReferences` and I-keys numbers. `commits` = PR commit shas; `merge_sha` = merge/squash commit or null. `author` = sha256(login)[:12] (impact hashes emails, so authors do not join across the two).

## I-issue: issue record
`state` `open`/`closed`, `state_reason` lowercased (`completed`, `not_planned`, ...) or null. `prs` = fetched PRs whose `issues` holds it; `session_ids` = union of those PRs' sessions.

## I-type: ticket type
First label (case-insensitive) in `TYPE_LABELS`; an untyped PR takes the type of its first typed closing issue; else null (`none` in the summary).

## I-join: PR to sessions
Index of linked impact records (`link_p` non-null; pending window candidates are ignored): `(repo_label, sha) → session_id`. A PR's sessions = sessions owning any of its commit shas or its merge sha (a squash commit pulled locally and linked by impact).

## I-cost: spend
PR cost = Σ over its sessions of session `cost.total` × (that session's commits matched in this PR / that session's linked commits across all impact records). An issue gets cost/k of each closing PR that closes k issues. Rounded to 6 decimals. Summing PR cost never counts a session twice; summing issue cost misses PRs without issues.

## I-summary: issues_summary.json
`prs`, `prs_merged`, `prs_with_session`, `prs_without_ticket` (no `issues` and no `keys`: the share the pitfall in `../issue-trackers.md` asks for), `issues`, `issues_closed_without_pr`, `cost_linked` = Σ PR cost, `truncated`, `by_type` = per type (null → `none`): PR count, issue count, distinct sessions and Σ cost of its PRs.

## I-ex: worked example (`../tests/test_issues.py`, `../tests/fixtures/issues/`)
Impact: s-a linked [a1, a2] ($2), s-b pending [b1] ($1), s-c linked [c1] ($0.50). PRs: #10 merged, label bug, title "(#3)", commit a1 → bug, issues [3], s-a, $1.0; #11 "PROJ-42", commits a2+b1, closes 4 and 5 → type feature from issue 4's label `Enhancement`, $1.0 (b1 pending, ignored); #12 closed, branch `12-wip` (no issue 12) → ticketless, $0; #13 merge sha c1 → s-c, $0.5, ticketless; #9 older than the window, paging stops before page 3. Issues: 3 ($1.0), 4 and 5 ($0.5 each), 6 not_planned with no PR, 7 open. Summary: 4 PRs, 3 merged, 3 with a session, 2 without ticket, 5 issues, 1 closed without PR, cost 2.5.
