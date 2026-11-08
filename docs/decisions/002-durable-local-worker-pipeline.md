# ADR 002: durable local worker pipeline before distributed infrastructure

## Status

Accepted

## Context

Snapshot analysis should not keep an HTTP request open while a ZIP is inspected and images are decoded. The project also needs observable states for duplicate delivery, retries, worker failure and permanent input errors. Requiring Kafka, Redis and cloud object storage would make the portfolio demo harder to run and would hide the core state transitions behind infrastructure configuration.

## Decision

TraceHarbor persists each build and analysis job in SQLite, stores the uploaded ZIP behind a content-addressed object-store interface, and processes jobs in a bounded thread pool. Claims are atomic and use expiring leases. Transient failures requeue with bounded exponential backoff; validation failures are terminal. Submission idempotency is enforced by a unique `(project, idempotency_key)` constraint.

## Consequences

- The complete failure model is reproducible with one command and testable without network services.
- A crashed worker does not permanently strand a running job.
- Duplicate CI delivery does not create duplicate analysis work.
- SQLite and process-local workers limit this implementation to one service node.
- The design demonstrates task-queue semantics but does not claim Kafka, Redis or distributed-worker experience.

The production migration path keeps the same domain states while replacing object storage, job transport and metadata persistence independently.
