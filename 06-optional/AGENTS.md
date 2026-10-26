# optional

Parts only some setups need. Nothing else depends on them; offer each one separately, after the basic install works.

- `identity.md` corporate login (Okta, Entra ID, Google Workspace) and user to team mapping.
- `mcp-server/` the analysis as MCP tools, so an agent can ask where spend goes (`server.py`), and `live.py` (`otm-live`) over the sessions and subagents running on this machine, for an orchestrating agent (`../00-docs/agents/orchestrate.md`).
- `decision-models.md` method and vendors for decision models that label events cheaply; the owner picks the vendor or a local model.
- `decide/` the decision points and vendor connectors: state, question, options -> probabilities. Sends the numeric state to the chosen vendor (jev hosted, d1 local). Replaces `decide.py` (now in `todelete/`).
- `tests/` unit tests for `decide/` and `mcp-server/`.
