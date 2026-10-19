# How OpenTokenMini works

## Root causes

1. Base models have no internal representation of agentic workflows, the tools they run on, or what those tools can do. They can't estimate how many turns, tokens or minutes a task will take, and harness system prompts tell them not to try.
2. Their pretraining data predates the shift to agentic work, so they have no view of how it is done today.
3. Efficient delegation topologies and workflows are not in context. Some may not be known yet, and each operator rediscovers them alone.
4. No semi-automated feedback loop tells whether a workflow or a delegation actually worked.
5. Neither the orchestrating loop nor the human operator has tools to see cost, context and impact.

1 and 2 are on the labs' side. OpenTokenMini works on 3 to 5, in dependency order: visibility first, then the feedback loop, then measured topologies injected into the agent's context.

Coding agents report every call over OTLP, the OpenTelemetry protocol most harnesses already speak. A collector stores those records where you choose, and dashboards, analysis and an MCP server for agents read from it.

<img src="architecture.svg" alt="Harnesses send OTLP to a collector on the dev machine, a team deployment or the organization; dashboards, analysis and an MCP server read from it">

- **Harnesses**: Claude Code, Codex, Antigravity, OpenCode and other open harnesses. A session includes its subagents. Setup per harness: [harnesses](../../02-measure/harnesses.md).
- **Collector**: on the dev machine, as a private team deployment, or for the whole organization. What one machine collects can sync periodically to the team or organization instance. One instance serving several teams needs permissions per team ([identity](../../06-optional/identity.md)).
- **What is sent**: metadata by default (tokens, cost, time, errors). Prompts and code only if you turn them on ([transcripts](../../02-measure/transcripts.md)).
- **Read side**: dashboards for people, the analysis, and an MCP server so agents can query the same data.

## Analysis method

From the whole harness down to single commits. Each level adds one data source, joined to sessions by user, time and repo.

These levels are reference defaults, not a fixed pipeline. Each team or user changes them to their preference through the orchestration agents: which levels run, what they group by, which data sources they join.

1. **Per harness**: spend, time and errors by harness and model. Telemetry only.
2. **Per session**: where tokens and time go inside a session and its subagents: context, cache, tool calls, MCP servers, retries.
3. **Per commit**: what each session changed in the codebase, and whether it merged ([version control](../../04-auto-analysis/git.md)).
4. **Against runtime and infrastructure**: whether a change made services slower, broke them or changed their cost ([observability](../../04-auto-analysis/cloud-logs.md), [CI](../../04-auto-analysis/deployments.md)).

Optional decision models label each session's intent and quality so the analysis can group by what people were trying to do ([decision models](../../06-optional/decision-models.md)). Full method: [analysis method](../../03-analyze/METHOD.md). Suggested changes and how they are measured: [recommendations](../../03-analyze/recommendations.md).
