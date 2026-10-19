# How OpenTokenMini works

## Root causes

What makes agent work inefficient today, and the premise **Open**Token**Mini** starts from:

1. **Models never saw agentic work.** Their training data predates agentic workflows, so they have no picture of how that work is done, the tools it runs on, or how many turns, tokens or minutes a task takes.

**Open**Token**Mini** works on the rest, in dependency order: visibility (4), then the feedback loop (3), then measured workflows put in the agent's context (2).

2. **Good workflows are not in context.** Efficient delegation topologies and workflows are not in context. Some may not be known yet, and each operator rediscovers them alone.
3. **No feedback loop.** No semi-automated feedback loop tells whether a workflow or a delegation actually worked.
4. **No visibility.** Neither the orchestrating loop nor the human operator has tools to see cost, context and impact.

## What you get

1. **Metrics Collection**: every call from every harness, stored where you choose. Everything else builds on it.
2. **Tools for Your Agent**: an MCP server and similar tools so the agent can optimize its own workflow and measure the impact of a change semi-automatically.
3. **Workflow Catalog**: ultra-efficient workflows, crowdsourced by everyone who uses the framework, that the agent can pull into its context.
4. **Interpretability and Automation**: views for the individual operator, the team and the organization, and automation so nobody has to re-explain a workflow to people every time.

## Architecture

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
