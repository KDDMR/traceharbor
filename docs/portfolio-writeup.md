# Building TraceHarbor: reliable telemetry and CI artifact processing

I built TraceHarbor to explore developer tooling end to end: how an application can report failures without depending on the monitoring system, and how a CI service can accept a screenshot build, process it asynchronously and return a useful comparison to an engineer.

The project combines a Python telemetry SDK, an ingest pipeline, issue grouping, durable analysis jobs, content-addressed artifact storage, pixel-level snapshot comparison and a small dashboard. I kept it runnable on one machine so that the complete state transition remains visible in code and tests.

The questions I focused on were:

- How does telemetry capture stay off the host application's request path?
- How can a large request body be stored without buffering it fully in memory?
- What should happen when CI delivers the same build more than once?
- How does a worker recover after losing ownership of a running job?
- Which failures deserve a retry, and which inputs should fail permanently?
- How can ZIP and image processing be bounded before expensive work begins?
- How can limitations be documented without claiming untested production scale?

## Decisions I made

The SDK places events in a bounded queue and sends batches from a background worker. Delivery uses bounded exponential backoff with jitter. Event IDs make repeated delivery idempotent, while deterministic server-side fingerprints group recurring failures.

The artifact API streams a declared content length to temporary storage in 1 MiB chunks while calculating SHA-256. It fsyncs the file and moves it atomically into a content-addressed object directory. A project-scoped idempotency key maps retries to the original build and job.

Analysis jobs are persisted before the request returns. Workers claim jobs atomically, attach expiring leases and increment the attempt counter. A lost worker can therefore be replaced after the lease expires. Transient failures requeue with bounded exponential backoff, while malformed archives and unsafe paths fail immediately.

The snapshot analyzer checks entry counts, aggregate uncompressed size, duplicate names and traversal paths before decoding PNG files. Unchanged hashes bypass pixel work. Changed images are decoded to RGBA and compared pixel by pixel; the result distinguishes added, changed, removed and unchanged files.

## Boundaries and next steps

This repository demonstrates the state machine and failure behavior, not a claim of multi-GB production throughput. SQLite, a local content-addressed store and thread workers are appropriate for a reproducible single-node demo. The default upload limit is intentionally 50 MB.

For production, I would preserve the domain states while moving uploads to S3-compatible multipart storage, job delivery to Kafka or a managed queue, metadata to PostgreSQL and image work to independently scaled workers. I would benchmark memory and throughput with realistic archives before selecting concurrency and partitioning strategies. A GitHub App could then translate pull-request webhooks into idempotent builds and publish the completed result through the Checks API.

TraceHarbor is intentionally not presented as a replacement for Sentry. It is a compact engineering exercise that makes reliability, security, retries and scaling trade-offs inspectable.
