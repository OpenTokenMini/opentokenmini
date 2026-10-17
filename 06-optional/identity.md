# Identity

Placeholder. Corporate login in front of collector, dashboard and MCP server, and mapping of people to teams.

- Reads: identity claims (user, email, groups); team structure from directory sync.

## Coverage (tentative priority)

- First: Okta, Microsoft Entra ID, Google Workspace.
- Next: generic OIDC/SAML (Keycloak, Auth0, JumpCloud).
- Team mapping: SCIM or directory groups; fallback a CSV the owner maintains.

## Pitfalls

- Harness identity is the vendor account email, often not the corporate one; keep an alias table.
- Contractors and shared accounts break per-user metrics; mark them.
- Per-person views follow the privacy defaults in `../02-measure/METHOD.md`.
