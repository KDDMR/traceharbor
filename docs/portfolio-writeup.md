# Building TraceHarbor: reliable telemetry on both sides of the wire

I built TraceHarbor to explore a developer-tools problem end to end: how an application can report failures without making its own reliability depend on the monitoring system.

The project contains a Python SDK, an ingest pipeline, issue grouping, persistence and a small dashboard. The feature set is intentionally limited. I focused instead on the design questions that become important once telemetry leaves a demo script:

- How does capture stay off the request path?
- What happens when ingest is unavailable?
- How are retries made idempotent?
- Which dynamic errors should become the same issue?
- Where should credentials and identifiers be removed?
- How can failure behavior be tested deterministically?

## Decisions I made

The SDK places events in a bounded queue and sends batches from a background worker. Delivery uses bounded exponential backoff with jitter. When the retry budget is exhausted, the SDK counts the dropped events and keeps the host application running.

On the server, the entire envelope is prepared before the first write. This prevents a malformed later item from producing an accidental partial result. Common credential keys and email values are filtered before persistence. Event IDs are unique and inserts are idempotent, so a client can retry without increasing the issue count twice.

Issue grouping is server-owned. A fingerprint uses the exception type and top application frame while excluding dynamic values and line numbers. That choice is simple and explainable, and the included architecture notes describe where it would need to evolve for source maps, multiple SDK languages and distributed ingest.

## What I would build next

My next step would be a durable boundary between intake and processing. Stateless ingest nodes would authenticate, validate and append envelopes to a log. Consumers could then normalize stacks, symbolicate frames, group issues and write to stores chosen for their access patterns. I would also add a disk-backed SDK spool, scoped project keys, source map support and property-based tests for event normalization.

TraceHarbor is not presented as a replacement for a production observability platform. It is a compact engineering exercise that makes reliability, privacy and scaling trade-offs visible in code and tests.

