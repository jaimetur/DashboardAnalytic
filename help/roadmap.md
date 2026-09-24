# Product roadmap

## Available now

- Named, access-controlled workspaces.
- CDR ingestion, profiling, preview
- Vendor mapping datasets support.
- Region mapping polygon shapes support.
- Datasets Analysis analysis and exports.
- Ad-hoc Chart Builder.
- Ad-hoc Query Builder.
- Template-driven NSA/SA Dashboards and PPT Reports.
- Shared Interactive Preview and filtered-data viewer.
- Report Template management and validation.
- Unified background jobs.
- App Logs with user/system execution identity.
- Portable and server-to-server environment transfer.
- Responsive layouts for compact mobile screens.

## Planned product work

- Approved scoring and GAP-analysis automation.
- Non-qualified calls Analysis module.
- Configuration datasets injestion to enrich CDR dataset and combine them to extract combined info using SQL Queries or Report Templates.
- Additional validated KPI/chart contracts.
- Smart Orchestrator Logs Reports.

## Architecture considerations

Potential future scaling work:

- external background-worker queue;
- durable analytical caches;
- database/storage options for heavier concurrency;
- stronger observability for long-running processing;
- automated end-to-end deployment verification.

Roadmap items are intentions, not commitments for a specific release. Refer to the Changelog for delivered behaviour.
