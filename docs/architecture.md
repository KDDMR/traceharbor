# Architecture and production evolution

## Goals

TraceHarbor demonstrates an understandable telemetry path with production-minded boundaries. The project prioritizes correctness, failure isolation and inspectability over feature breadth.

The key invariants are:

1. Capturing telemetry should not crash the host application.
2. Invalid envelopes should fail before any event in that envelope is persisted.
3. Common credentials and direct identifiers should be filtered before storage.
4. Retried event IDs should be idempotent.
5. Grouping should remain stable when exception messages contain dynamic values.
6. Retried artifact submissions should resolve to the original build and job.
7. Artifact request bodies should be streamed, bounded and validated before analysis.
8. At most one worker should own an analysis job until its lease expires.

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

### Artifact ingest and object storage

The artifact endpoint accepts `application/zip` and requires a project-scoped idempotency key. It reads exactly the declared content length in 1 MiB chunks, calculates SHA-256 while writing, fsyncs the temporary object, and atomically moves it into a content-addressed directory. Identical files therefore share one stored object without making the API response dependent on filename choices.

The local implementation intentionally exposes an object-storage boundary instead of passing filesystem paths into the HTTP adapter. A production implementation can replace it with S3 multipart upload while preserving the submission and analysis services.

### Durable analysis queue

Build metadata and analysis jobs are created in one database transaction. Workers claim one due job under `BEGIN IMMEDIATE`, increment its attempt count and attach an expiring lease. A process failure leaves the job reclaimable after that lease expires. Transient failures requeue with bounded exponential backoff; malformed archives are permanent failures and are not retried.

The bounded thread pool demonstrates the task-system failure model without requiring external infrastructure for the local demo. It is not presented as a distributed queue.

### Snapshot comparison

Before decoding images, the analyzer rejects path traversal, duplicate paths, excessive entry counts and excessive aggregate uncompressed size. PNG contents are validated with Pillow. SHA-256 avoids pixel work for unchanged files; changed images are decoded to RGBA and compared at pixel level. Size changes count as a complete difference. Results distinguish baseline, unchanged, changed, added and removed snapshots.

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
| Local content-addressed files | Multi-GB uploads, regional durability | S3-compatible multipart upload with lifecycle policies |
| SQLite job table | Multiple worker deployments and high throughput | Kafka or managed queue plus PostgreSQL job metadata |
| Thread worker pool | CPU isolation and independent scaling | Separately deployed workers with autoscaling and backpressure |
| Pillow pixel loop | Tens of thousands of large images | Parallel chunking, native image kernels and benchmark-driven batching |

## Failure model

- **Ingest unavailable:** the SDK retries a bounded number of times and drops telemetry rather than blocking indefinitely.
- **Duplicate delivery:** event IDs make persistence idempotent.
- **Malformed envelope:** validation rejects the full envelope before writes.
- **Storage exception:** the SQLite transaction rolls back both event and issue changes.
- **Excess traffic:** token-bucket limits return `429` with `Retry-After`.
- **Sensitive fields:** recognized keys and email values are filtered before validation and persistence.
- **Duplicate artifact request:** the project and idempotency key return the original build/job pair.
- **Worker process loss:** the lease expires and another worker may reclaim the job.
- **Transient analysis failure:** the durable job is requeued with bounded backoff and attempt count.
- **Malformed or unsafe ZIP:** the build fails permanently without retrying.
- **Oversized upload:** compressed size is rejected before streaming; uncompressed size is checked before image decoding.

The explicit drop counter in the SDK is the beginning of self-observability. A mature client would expose transport health, queue saturation and discarded-event reasons to debug logs or an application callback.

