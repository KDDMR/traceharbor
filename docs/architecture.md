# Architecture and production evolution

## Goals

TraceHarbor demonstrates an understandable telemetry path with production-minded boundaries. The project prioritizes correctness, failure isolation and inspectability over feature breadth.

The key invariants are:

1. Capturing telemetry should not crash the host application.
2. Invalid envelopes should fail before any event in that envelope is persisted.
3. Common credentials and direct identifiers should be filtered before storage.
4. Retried event IDs should be idempotent.
5. Grouping should remain stable when exception messages contain dynamic values.

## Components

### Python SDK

The SDK creates a bounded in-memory queue and a daemon delivery thread. Events are sent in envelopes according to a batch-size or time threshold. The transport uses bounded exponential backoff with jitter, protecting the monitored application from an indefinitely unavailable ingest service.

The SDK accepts a transport interface rather than constructing network behavior inside the client. Tests can therefore exercise batching and retry state without sleeping or binding ports.

### Ingest API

The HTTP adapter is intentionally thin. It authenticates the caller, enforces byte limits, parses JSON and maps domain errors to status codes. `TelemetryService` owns the use case: authorize, rate-limit, prepare every event, then persist it.

Preparing the complete envelope before writing avoids partial acceptance when the second or later event is invalid. A production protocol might instead expose per-item status; that would be a deliberate API change rather than an accidental side effect.

### Processing

Untrusted payloads pass through recursive privacy filtering and schema validation. Error fingerprints use the project, exception type and highest application frame. They deliberately exclude line numbers and exception values because both often change without changing the underlying issue. Message fingerprints normalize long numbers and UUIDs.

This heuristic is explainable and deterministic. It is not a substitute for source-map-aware stack processing, frame classification or learned grouping.

### Persistence

SQLite runs in WAL mode. Inserting an event and updating its issue happen in one transaction under a process-local lock. `INSERT OR IGNORE` makes retries with the same event ID idempotent. This is robust for a local single-node demonstration and creates a clear seam for replacing persistence later.

## Production evolution

| Current design | Scaling pressure | Production direction |
|---|---|---|
| In-memory SDK queue | Process termination loses buffered events | Optional disk spool with strict quota |
| Single HTTP process | CPU and connection limits | Stateless ingest replicas behind a load balancer |
| In-process token buckets | Limits differ by replica | Shared limiter in Redis or edge gateway |
| Synchronous SQLite write | Burst traffic and write contention | Durable log such as Kafka, async consumers |
| SQLite query model | High-cardinality analytical queries | Columnar event store plus issue metadata store |
| Basic frame fingerprint | Source maps and library noise | Stack normalization, frame ownership, adaptive grouping |
| Static API key | Rotation and project isolation | Scoped project keys, rotation and audit trail |

## Failure model

- **Ingest unavailable:** the SDK retries a bounded number of times and drops telemetry rather than blocking indefinitely.
- **Duplicate delivery:** event IDs make persistence idempotent.
- **Malformed envelope:** validation rejects the full envelope before writes.
- **Storage exception:** the SQLite transaction rolls back both event and issue changes.
- **Excess traffic:** token-bucket limits return `429` with `Retry-After`.
- **Sensitive fields:** recognized keys and email values are filtered before validation and persistence.

The explicit drop counter in the SDK is the beginning of self-observability. A mature client would expose transport health, queue saturation and discarded-event reasons to debug logs or an application callback.

