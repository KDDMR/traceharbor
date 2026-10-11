# ADR 001: Group issues on the ingest side

- Status: Accepted
- Date: 2026-10-11

## Context

Events need a stable issue identity so repeated failures appear as one actionable problem. A fingerprint could be generated in the SDK, in the ingest service or by an asynchronous consumer.

## Decision

TraceHarbor computes a deterministic fingerprint in the ingest service after privacy filtering and validation.

For exceptions, the default input is project, exception type, filename and function of the top frame. For messages, dynamic numeric and UUID values are normalized before hashing. SDK callers may provide a custom fingerprint when domain knowledge is stronger than the default heuristic.

## Consequences

- Grouping policy is consistent across future SDK languages.
- Policy changes do not require a client release.
- Raw events can be reprocessed under a later algorithm, assuming retention permits it.
- The synchronous ingest path does more work.
- The demo cannot independently scale grouping consumers.

At larger scale, the same policy would move behind a durable queue while remaining server-owned.

