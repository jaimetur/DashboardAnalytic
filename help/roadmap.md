# Product roadmap

## In this guide

| Task or topic | Go to |
| --- | --- |
| Available now | [Open section](#available-now) |
| Planned product work | [Open section](#planned-product-work) |
| Architecture considerations | [Open section](#architecture-considerations) |

## Available now

> [!NOTE]
> **Available versus planned.** The first section describes existing capabilities. Planned items are future work, not features available in the current release.

- Named, access-controlled workspaces.
- CDR ingestion, profiling, preview
- Vendor mapping datasets support.
- Region mapping polygon shapes support.
- CDR Analysis analysis and exports.
- Ad-hoc Chart Builder.
- Ad-hoc Query Builder.
- Template-driven NSA/SA Dashboards and PPT Reports.
- NetCheck City/Road Scoring & GAP Analysis with persistent jobs, aggregation controls and CSV/PPT exports.
- Shared Interactive Preview and filtered-data viewer.
- Report Template management and validation.
- Unified background jobs.
- App Logs with user/system execution identity.
- Portable and server-to-server environment transfer.
- Responsive layouts for compact mobile screens.

## Planned product work

- Non-Qualified Calls: confirm the NQ definition (currently every result other than Completed) and add its reports to Reporting Jobs.
- Configuration datasets ingestion to enrich CDR dataset and combine them to extract combined info using SQL Queries or Report Templates.
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
