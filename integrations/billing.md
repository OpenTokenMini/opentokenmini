# Billing

Placeholder. Actual spend from vendors, to reconcile with the estimates in telemetry.

- Reads: cost and usage per day, per API key or workspace, per model; seat counts.

## Coverage (tentative priority)

- First: Anthropic Admin API (usage and cost), OpenAI usage and costs API.
- Cloud model hosting: AWS Bedrock (Cost and Usage Report), Google Vertex AI (billing export), Azure OpenAI (Cost Management).
- Seat-based: Cursor, GitHub Copilot, Claude and ChatGPT plans (seat count times price).

## Pitfalls

- Telemetry cost is list price per call; invoices include discounts, commitments and seats. Report both, never mix them.
- Billing lags hours to a day.
- API keys shared across teams make billing per team impossible without telemetry.
