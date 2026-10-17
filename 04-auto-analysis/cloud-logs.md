# Observability

Placeholder. Infra and service signals around agent-made changes: deploys, latency, error rates, incidents. Also a possible destination for telemetry instead of `../02-measure/collector.py`.

- Reads: deploy events, service metrics and incidents by service and time.

## Coverage (tentative priority)

- First: Datadog, Grafana stack (Prometheus, Loki, Tempo), any OpenTelemetry Collector.
- Next: New Relic, Elastic, Honeycomb, Splunk; cloud-native (CloudWatch, Google Cloud Monitoring, Azure Monitor).
- Incidents: PagerDuty, Opsgenie, incident.io.

## Pitfalls

- Linking an incident to a change needs deploy markers with the commit SHA; without them, report correlation only.
- Correlation is not cause: dashboards show "changes before incident", never "caused by".
- As destination: storing raw telemetry there is costly per GB; send aggregates if the owner prefers.
