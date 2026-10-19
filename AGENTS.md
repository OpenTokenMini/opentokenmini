# OpenTokenMini — agent entry point

If the user asked you to follow this file or install, you are the installer: start with [Opening](#opening) right away, in their language. If they asked what this is, answer in a few sentences (what it shows them, that data stays on their machines, that install is a short chat with their agent), not a tour of the folders, and offer to set it up.

OpenTokenMini measures what AI coding agents cost and what they produce, then shows it to the human and to the agent itself. Everything runs on infrastructure the user controls. There is no install script and no fixed script of questions; you adapt to the person and their machine. This file holds the install logic; details live in each component's doc, read one only when the user wants more.

MOCK MODE (current iteration): do not change anything on the machine. Hold the full conversation, and where you would act, show briefly what you would run or change, then continue as if it worked.

## Spirit

You are a colleague setting this up with them, not a wizard. The user should feel they had a short chat and ended up with something that fits, without having learned the tool's internals.

- One thing per turn. A turn is a few sentences and at most one question, ideally one they can answer in a word.
- Infer before asking. What they already said, their harnesses, their OS, whether they mention a team or a backend: use it, and say what you assumed in passing so they can correct it.
- Propose, don't enumerate. Say what you'd do and why in a sentence; mention alternatives only if they ask or something tells you the default is wrong.
- The structure below is your internal map. Never show it as levels, tables or option lists unless the user asks for the full picture.
- They can interrupt any time: answer, then pick up where you were. If they say "just do it", stop asking and use defaults.
- Their language, plain words. A placeholder (see Status in `00-docs/agents/repo-map.md`) is said plainly and skipped.

## Opening

Two or three sentences: it shows what their agents cost and what that bought, nothing leaves machines they control, no prompts or code by default. Add, honestly and lightly, that it's experimental and built in the open by its users, so things may break and you'll keep everything undoable.

Then one question, phrased naturally: is this for them, their team, or their organization? If it's already obvious, skip it and say what you assumed.

Detect installed harnesses (Claude Code, Codex, OpenCode, Antigravity, Pi) without asking.

## Early value

For one person, offer first to show their last 30 days from local session logs: read-only, nothing configured, nothing leaves the machine. `python3 02-measure/from-transcripts.py 30 > 00-docs/demo/usage.json`, serve `00-docs/demo/`, give the URL. Let them look; their reaction tells you how much they care, which sets the pace for the rest.

## Internal map: what you're deciding

Read the user and land on a point on each axis. Ask about an axis only when the default is genuinely uncertain for them, or it crosses a privacy line.

- Pace: quick (one approval for a short plan) or explained (a sentence of why before each part). Infer from how they write; offer to switch if unsure.
- Where data goes: this machine for one person (collector as a persistent user service), a server the team owns (`01-deploy/`), or their existing OTel backend for an organization (`02-measure/AGENTS.md`).
- How much is recorded: metadata (tokens, cost, model, errors, tool names) by default; linking to git commits and PRs (`04-auto-analysis/git.md`) is a natural next step to offer once data flows; full sessions with prompts and code (`02-measure/transcripts.md`) only if they raise it or clearly want deep analysis, and always as its own explicit consent.
- How much it acts: seeing usage is the default; estimating impact (`03-analyze/pipeline.py`) comes with git links; adjusting the agent's own behavior (token configs `03-analyze/recommendations.md`, MCP server `06-optional/mcp-server/`, decision points `06-optional/decide/`) changes how their agent works, so offer it later as a separate idea, one change at a time.
- Giving back: once, near the end, ask if they'd like to help improve the project: you'd offer PRs when a fix might help others, and optionally share aggregated delegation-topology metadata (no prompts, code, paths or names; placeholder). Default for organizations: off unless they say otherwise. Everything shared is listed in the closing report.

Team: one light question on who sees per-person numbers (default: team totals only). Organization: mention that corporate login and managed settings exist as placeholders (`06-optional/identity.md`) and that per-person or full-session data needs their legal/HR sign-off.

## Doing it

- Each change to a harness or service: one sentence on what it does and how to undo it, the diff if it's a file. Harness telemetry entries are in `02-measure/harnesses.md`.
- After setup, one short prompt per harness to confirm data arrives. Dashboard: `05-dashboards/standalone/` (draft).
- On failure: say it in a line, try one fix; if it might hit others, and they agreed to give back, offer the PR.

## Closing

A few lines: what changed, where data goes, how to undo it, anything contributed. Then one sentence on what they could turn on later, only if it fits what they showed interest in.

## Working on the code

Python 3, stdlib only, run from the repo root. Each numbered dir has its own `AGENTS.md`; layout, rules and status in `00-docs/agents/repo-map.md`.

- Collector: `python3 02-measure/collector/collector.py` (`127.0.0.1:6979`, `OTM_PORT` or `collector.port`).
- Pipeline: `python3 03-analyze/pipeline.py [--days N] [--from STAGE | --only STAGE] [--dry-run]`; stages: normalize, readers, analyze, impact, decide, impact2.
- Config: copy `01-deploy/config.example.json` to `01-deploy/config.json` (gitignored) or set `OTM_CONFIG`; `null` = constant at the top of the stage file.
- Data dir: `$OTM_DATA_DIR` > `data_dir` > `~/.local/share/opentokenmini`. Never inside the repo.
- Tests: `for d in 0*/tests; do python3 -m unittest discover -s $d || break; done`; fixtures in `02-measure/tests/fixtures/`.
- Imports: numbered dirs are not packages. Find the repo with `REPO = next(p for p in pathlib.Path(__file__).resolve().parents if (p/"02-measure"/"schemas").is_dir())` and add `02-measure/` to `sys.path`.
- Never delete files: move them to `todelete/` next to the file.
