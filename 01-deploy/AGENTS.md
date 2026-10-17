# deploy

Placeholder. Where the service (`../02-measure/`, `../03-analyze/`, `../05-dashboards/`, `../06-optional/mcp-server/`) runs. Recipes, not scripts: the user's agent adapts them to local infra rules.

- Input: target environment and its rules.
- Output: running service, endpoint URL, auth.
- Data it touches: the chosen host only.

## Coverage (tentative priority)

- Local trial: `python3 ../02-measure/collector.py`.
- First team rollout: Docker Compose on one VM.
- Managed containers: AWS (ECS Fargate), Google Cloud Run, Azure Container Apps.
- Kubernetes: Helm chart.
- Existing backend: harnesses point at Datadog, Grafana or an OpenTelemetry Collector (`../04-auto-analysis/cloud-logs.md`); analyze reads from there.

## Checklist

`checklist.md`: what a deployment has, lacks, or could add. Start and end every install by reading it.

## Workflow

1. Ask: where, who can reach it, data region, retention.
2. Deploy, put TLS and auth in front (`../06-optional/identity.md`).
3. Verify with a test record end to end.
4. Hand endpoint and auth to the workstation install (`../02-measure/AGENTS.md`).

## Pitfalls

- Laptops must reach the endpoint: VPN, zero-trust proxy, or a public TLS endpoint with a token.
- Endpoint down means silent data loss on workstations; monitor ingest rate, alert on drop to zero.
- Clock skew between machines breaks session to commit linking; store server receive time too.
- Backups and retention are the owner's call; state the defaults.
