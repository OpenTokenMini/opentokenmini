# quality: specs

Constants at the top of `quality.py`: `DAYS=7`, `ROOT`, `REWORK_HOURS=24`, `SHELL_TOOLS=("Bash",)`, `EDIT_TOOLS=("Edit","Write","MultiEdit","NotebookEdit")`, `TEST_RX`, `FAIL_RX`, `RISK_RX`, `LOCAL_RX`.

## Q-read: what is read
Claude Code transcript files modified since now − `--days`; lines with a `tool_use` or `tool_result` block whose `timestamp` ≥ that cutoff. Grouped by `sessionId` (subagent transcripts carry their parent's id, so they count with it). Per `tool_use`: name, ts, `input.command` (only for `SHELL_TOOLS`), `input.file_path`/`notebook_path` (only for `EDIT_TOOLS`, realpath). A `tool_result` is paired by `tool_use_id`; its text (string, or the `text` of its blocks) is used only for Q-test and then dropped. Session `start`/`end` = first/last such line. `repo_label` = basename of the first cwd seen.

## Q-tool-error: tool error rate
`tool_calls` = tool_use blocks; `tool_errors` = those whose result has `is_error: true` (Claude Code sets it for a non-zero exit, a refused permission, a missing file, a failed edit). `tool_error_rate = tool_errors/tool_calls`, null when 0. A call without a result counts as a call, not an error.

## Q-test: test runs
A shell call whose command matches `TEST_RX` (unittest, pytest, npm/yarn/pnpm/bun test, go/cargo/make/mvn/gradle test, jest, vitest, rspec). Failed = result `is_error` or result text matches `FAIL_RX` (`FAILED (`, `N failed`, `FAIL:`, `--- FAIL`, `test result: FAILED`); the text check catches `| tail` pipes that hide the exit code. Passed otherwise. `test_runs`, `test_failed`; `last_test` = result of the session's last run (by tool_use ts), null if none.

## Q-risk: risky commands (`../quality.md` first candidate)
Per shell command, per class, a match of `RISK_RX[class]` counts once: `destructive` (`rm -rf`, `git reset --hard`, force push, `git clean -f`, `git branch -D`, `git checkout -- .`, `mkfs`, `dd if=`, `drop table`); `exfiltration` (curl sending data, `scp`, `nc`, `wget --post`, `rsync` to `host:`), not counted when the matching line names a local host (`LOCAL_RX`); `secrets` (`.env`, ssh keys, `.aws/credentials`, `.netrc`, `printenv`, `API_KEY|SECRET|TOKEN|PASSWORD`). Why the local exception: on real data (7 days) it removed 13 of 23 exfiltration hits, curl POSTs to local dev servers.

## Q-rework-session: files reworked by a later session
A file edited by session S is reworked when a different session edits it later, within `REWORK_HOURS` of an edit by S. `files_edited` = distinct files S edited; `files_reworked` = those reworked. Edits within the same session are iteration, not rework.

## Q-commit: commit records
One per commit of an impact record with non-null `link_p` (pending window candidates are ignored, as in issues I-join). Carries `harness`, `session_id`, `repo_label`, `sha`, `ts` and `reverted_by` from impact.

## Q-test-last: test state at commit time
`last_test` = result of the session's last test run with ts ≤ commit ts; null when the session ran no test before it.

## Q-rework-commit: commits reworked soon after
Repos = `--repo` + config `impact.repos` + git toplevels of session cwds and edited files' dirs; only those whose basename is an impact `repo_label` are scanned, with `git log --all --no-merges --name-only` from the cutoff − `REWORK_HOURS`. `reworked_by` = shas of later commits (any author) within `REWORK_HOURS` that touch at least one file of the commit; null when the commit is not in a scanned log. File-level, so an upper bound on "touched agent-written lines" (line-level via blame is next).

## Q-summary: quality_summary.json
`sessions`, `tool_calls`, `tool_error_rate` = Σ errors/Σ calls; `sessions_with_tests`, `test_runs`, `test_fail_rate` = Σ failed/Σ runs; `file_rework_rate` = Σ files_reworked/Σ files_edited; `risky` = Σ per class; `commits`; `commit_rework_rate` = commits with non-empty `reworked_by` / commits with non-null `reworked_by`; `commits_last_test_fail`; `commits_without_test`. Rates rounded to 6 decimals, null when the denominator is 0.

## Q-ex: worked example (`../tests/test_quality.py`, `../tests/fixtures/quality/`)
s1 (10:00–10:25): unittest → `FAILED (failures=1)` (fail, via text); edit a.py; pytest → `3 passed`; `rm -rf build`; curl -d to an external host; curl -d to localhost (not counted); `cat .env`; a Read with `is_error`; write b.py. s2: edit a.py at 20:00 (reworks s1's a.py); `npm test` with `is_error`; edit b.py two days later (outside `REWORK_HOURS`). Git: c1 a.py 10:15, c2 b.py 10:28 (both linked to s1), c3 a.py 18:00, c4 b.py two days later (s2, pending).
s1: 9 calls, 1 error, 2 tests 1 failed, last pass, risky 1/1/1, files 2 reworked 1. s2: 1 test failed, files 2 reworked 0, no commits. c1: last_test fail (only the 10:00 run precedes it), reworked_by [c3]; c2: pass, []. No record for c4. Summary: 12 calls, error rate 0.166667, 3 tests, fail rate 0.666667, file rework 0.25, commit rework 0.5.
