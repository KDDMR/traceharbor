# Contributing

TraceHarbor is a compact portfolio project, but changes follow the same habits as a shared production repository.

## Development workflow

1. Install development dependencies with `python -m pip install -e ".[dev]"`.
2. Create a focused branch: `git switch -c feat/short-description`.
3. Keep public HTTP and event contracts backward compatible or document the migration.
4. Add tests for both the expected path and failure behavior.
5. Run `make check` before opening a pull request.
6. Explain observability, privacy and persistence trade-offs in the pull request.

Commits should be small, imperative and scoped where useful, for example `feat(sdk): add bounded delivery retries`.

## Design expectations

- The SDK must not crash or materially delay the host application.
- Untrusted payloads are validated before persistence.
- Credentials and direct identifiers are filtered before storage.
- Duplicate event IDs remain idempotent.
- Artifact request bodies stay bounded and stream instead of being buffered in memory.
- Duplicate artifact submissions preserve the original build and job identity.
- Workers may only commit results while they own the active lease.
- New dependencies need a concrete benefit and a documented trade-off.

