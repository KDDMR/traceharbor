# Security policy

This repository is an educational observability prototype, not a hosted service. Do not send real credentials, personal data or production telemetry to a public deployment.

## Built-in safeguards

- API-key authentication for ingest routes
- Request-size and envelope-size limits
- Per-key token-bucket rate limiting
- Recursive filtering of common credential fields and email addresses
- Parameterized SQL statements and UUID-based event identifiers
- Non-root container execution

The default `dev-key` is intentionally local-development only. A deployment must supply `TRACEHARBOR_API_KEY` through a secret manager and terminate TLS at a trusted proxy.

To report a vulnerability, open a private security advisory on the repository rather than a public issue.

