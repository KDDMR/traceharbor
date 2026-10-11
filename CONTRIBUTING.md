# Contributing

TraceHarbor is a compact portfolio project, but changes follow the same habits as a shared production repository.

## Development workflow

1. Create a focused branch: `git switch -c feat/short-description`.
2. Keep the public event contract backward compatible or document the migration.
3. Add tests for both the expected path and failure behavior.
4. Run `make check` before opening a pull request.
5. Explain observability, privacy and persistence trade-offs in the pull request.

Commits should be small, imperative and scoped where useful, for example `feat(sdk): add bounded delivery retries`.

## Design expectations

- The SDK must not crash or materially delay the host application.
- Untrusted payloads are validated before persistence.
- Credentials and direct identifiers are filtered before storage.
- Duplicate event IDs remain idempotent.
- New dependencies need a concrete benefit and a documented trade-off.

