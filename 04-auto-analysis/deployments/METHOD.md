# deployments: specs

Constants at the top of `deployments.py`: `DAYS=30`, `MAX_RUNS=500`, `MAX_FAILED_DETAIL=20`, `CI_DEFAULT="github_actions"`, `RUN_FIELDS`, `FAILED`, `PASSED`.

## D-repo: which repos
`--repo` values, else config `impact.repos`, else the current dir. A value that is an existing directory is a local clone: gh runs with it as cwd (gh resolves the GitHub repo from its remote) and `repo_label = basename(realpath)`, which is how impact labels repos. Anything else is passed as `gh -R OWNER/NAME` with `repo_label = NAME`. A repo whose gh call fails (not authenticated, no GitHub remote, no access) is skipped with a stderr line; the others still run.

## D-scan: run metadata
`gh run list --limit MAX_RUNS --created >=<since date> --json RUN_FIELDS`, then runs with `createdAt < since` dropped (since = now − `--days`). Kept per run: `run_id` (databaseId as string), `workflow`, `event`, `head_sha` (lowercase), `head_branch`, `status`, `conclusion` (empty → null), `created` (UTC), `duration_s` = updatedAt − startedAt for completed runs, else null. gh 2.45 exposes no actor or attempt in `run list`; neither is stored. Commit subject (`displayTitle`) is not read.

## D-failed-step: why a run failed
For runs whose conclusion is in `FAILED`, up to `MAX_FAILED_DETAIL` per repo (oldest first), `gh run view <id> --json jobs`: `failed_step = "<job> / <step>"` of the first step in `FAILED` of the first job in `FAILED`; the job name alone if no step failed; null otherwise or beyond the cap.

## D-join: run to session
Index = (repo_label, commit sha) over `impact.jsonl` records with non-null `link_p` (trailer links, and window links decide confirmed). A run joins the record holding its `head_sha` in the same `repo_label`; exact match first, else either sha a prefix of the other. The record copies `session_id`, `harness`, `link`, `link_p` from that impact record; all four null when unmatched. Only the head commit counts: CI tests the tip of a push or PR.

## D-rate: failure rate
Over runs with conclusion in `FAILED ∪ PASSED` (cancelled, skipped, neutral and unfinished runs excluded): rate = failed / n, separately for runs with a session (`agent`) and without (`baseline`). Pitfall from `../deployments.md`: flaky tests make the rate noisy; read agent against baseline, not alone.

## D-ex: worked example (04-auto-analysis/tests/test_deployments.py, fixtures/deployments/)
since 2026-10-01. Runs: 99 (Sep 30, dropped); 101 push success at sha a (s-a, trailer, p 1.0), 150 s; 102 PR failure at sha b, impact holds b[:12] (s-b, window, p 0.8 by prefix), failed_step "test / unittest"; 103 failure at sha c, whose only linked record is in repo `other` and whose `app` record is pending (no session), failed_step "test"; 104 success at c (no session); 105 in progress (conclusion and duration null). Rates: agent 0.5 (n 2), baseline 0.5 (n 2).
