# <img src="00-docs/humans/logo.svg" width="32" height="32" alt=""> OpenTokenMini

[English](README.md) · [中文](00-docs/humans/zh/README.md) · [Español](00-docs/humans/es/README.md)

Know what your AI agents cost, and what you get for it. Site: [opentokenmini.org](https://opentokenmini.org/)

OpenTokenMini measures what every agent call costs, how long it takes and where it fails, links it to the commits it produced, and feeds that back to the agent so it delegates better. It works with Claude Code, Codex, open models or a mix, for one developer, a team or a company. Free and open source: you can read everything it collects.

## Try it

Paste this into your coding agent:

```
Clone https://github.com/OpenTokenMini/opentokenmini and follow its AGENTS.md
```

It explains each step and asks before turning anything on. Nothing is collected before that, and prompts and code are never collected by default. Add what you want to the prompt, like "only Claude Code" or "send it to our Grafana".

<img src="00-docs/humans/dashboard.png" alt="OpenTokenMini dashboard: cost, tokens and effectiveness for the organization, then per team with its top issues">

<!-- TODO: link 00-docs/demo/ once usage.json is reviewed -->

## Single user, teams and organizations

- **Single user**: runs on your machine, no server.
- **Teams**: one small server you own (Docker Compose on a VM). Per-person spend is visible only to that person; the team sees totals.
- **Organizations**: send it to the backend you already run (Datadog, Grafana, an OpenTelemetry collector), with corporate login and teams.

## Architecture

Coding agents report every call over OpenTelemetry, which most of them already speak. A collector stores it on your machine, on a team server or in your organization's backend. Dashboards, the analysis and an MCP server for agents all read from there. Details: [how it works](00-docs/humans/overview.md)

<img src="00-docs/humans/architecture.svg" alt="Harnesses send OTLP to a collector on the dev machine, a team deployment or the organization; dashboards, analysis and an MCP server read from it">

## Results

Measured cases from teams using it, and how to add yours: [use case reports](00-docs/use-case-reports/)

## Need help?

Deployment, corporate login, or finding where your tokens go: [contact us](https://forms.gle/cqjyqVN9qky4gQ5U6)
