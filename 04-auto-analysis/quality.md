# Quality attributes (optional)

Placeholder. Semi-automated analysis of functional and non-functional attributes of what agents produce: security, performance, usability, accessibility, maintainability.

- Input: agent events (tool calls, commands, diffs when enabled), merged changes.
- Output: findings per session or change, with a probability from a decision model or a check result.
- Data it touches: depends on measure level; command text and diffs only when the owner enabled them.

Runs in two places:

- Workstation hooks (pre-commit, harness hooks), distributed from the service.
- Service batch over sessions and merged changes.

First candidate: classify every permission decision and command (destructive, data exfiltration, secrets, risky approval without review).
