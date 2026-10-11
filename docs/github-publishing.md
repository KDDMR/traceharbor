# Application links

TraceHarbor is published as a public portfolio project:

- Repository: https://github.com/KDDMR/traceharbor
- Technical write-up: https://github.com/KDDMR/traceharbor/blob/main/docs/portfolio-writeup.md
- Architecture notes: https://github.com/KDDMR/traceharbor/blob/main/docs/architecture.md
- Design decision: https://github.com/KDDMR/traceharbor/blob/main/docs/decisions/001-server-side-grouping.md
- Continuous integration: https://github.com/KDDMR/traceharbor/actions

## What reviewers can inspect

The repository demonstrates an end-to-end telemetry system: a zero-dependency Python SDK, authenticated ingest API, privacy filtering, deterministic issue grouping, transactional SQLite persistence, a browser dashboard, automated tests and container delivery.

Before sharing the repository in an application, confirm that the latest GitHub Actions run is green and that no generated database files are tracked.
