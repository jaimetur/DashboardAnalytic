<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="DriveTest Analyzer logo" width="320">
</p>

# DriveTest Analyzer Help

> [!TIP]
> **Start with your task.** Choose a guide below, then use its task index or the Page Sections navigation to reach the relevant workflow.

Use this Help centre for detailed workflows, examples and technical rules. For a shorter introduction and deployment quick start, open the **Readme** tab.

Help Navigation groups chapters under General, Main Modules, Administrative Modules and Reference. Help is available without signing in; only the PPT Reporting (old) chapter requires that feature.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Choose where to start | [Open section](#choose-where-to-start) |
| Documentation map | [Open section](#documentation-map) |
| Fast troubleshooting | [Open section](#fast-troubleshooting) |

## Choose where to start

| Your task | Recommended guide |
| --- | --- |
| New to the product | [Product Overview](overview.md) |
| Comparing results with another tool | [Technical Considerations](technical-considerations.md) |
| Installing the service | [Deployment Configuration](configuration.md) and [Docker Deployment](docker-deployment.md) |
| Uploading data | the [Data Ingestion](workspace-management.md#data-ingestion) section in Workspace Management |
| Analysing one dataset | [CDR Analysis](datasets-analysis.md) |
| Exploring a complete template as a live dashboard or generating its PowerPoint | [PPT Dashboards](ppt-dashboards.md) |
| Scheduling reports and emailing them | [Reporting](reporting.md) |
| Generating persistent Reports or Chart Sets | [PPT Reporting (old)](ppt-reporting-old.md) |
| Calculating NetCheck scores or comparing operator gaps | [Scoring & GAP Analysis](scoring-gap-analysis.md) |
| Building ad-hoc SQL queries with guided controls | [Query Builder](query-builder.md) |
| Authoring templates | [Workspace Config](workspace-config.md), including the [Report Template reference](workspace-config.md#report-template-reference) |
| Managing users and transfers | [Administrator Config](administrator-config.md) |
| Changing application-wide runtime settings | [Application Config](app-config.md) |
| Managing templates and chart mappings for a workspace | [Workspace Config](workspace-config.md) |
| Reviewing application and workspace activity | [App Logs](app-logs.md) |

## Documentation map

- [Product Overview](overview.md) — detailed tour of every module and panel.
- [Technical Considerations](technical-considerations.md) — normalisation, execution semantics, vendor mapping, storage, Dashboard caching and jobs.
- [Deployment Configuration](configuration.md) — runtime/rendering variables, storage roots, Docker settings and initial access.
- [Docker Deployment](docker-deployment.md) — production, development, persistence and upgrades.
- [Web Interfaces](web-interface.md) — shared navigation, dialogs, tables and responsive behaviour.
- [Workspace Management](workspace-management.md) — workspaces, data ingestion, processing, previews and mappings.
- [CDR Analysis](datasets-analysis.md) — interactive single-dataset analysis and exports.
- [PPT Dashboards](ppt-dashboards.md) — saved Dashboards, synchronized filters and slide layouts.
- [PPT Reporting (old)](ppt-reporting-old.md) — classic Reports, Chart Sets, interactive previews and jobs.
- [Non-Qualified Calls](non-qualified-calls.md) — the NQ Analysis Center: summary, NQ rate by campaign and operator, lifecycle and phases, root cause analysis and sources, drill-down and shared follow-up (status set by rules or by hand, team, assignee, root category and cause recommended from the RCA script, NetCheck and previous decisions, fields by section and comments) of every call and test that did not complete, across Daily and Final CDRs.
- [Reporting](reporting.md) — scheduled Reporting Jobs that email CDR Analysis, Network Insights, Dashboard and Scoring artifacts.
- [Chart Builder](chart-builder.md) — temporary ad-hoc chart construction.
- [Query Builder](query-builder.md) — guided query design, SQL editing, execution and saved queries.
- [App Logs](app-logs.md) — workspace events and live server output.
- [Application Config](app-config.md) — application-wide runtime settings and their effect.
- [Workspace Config](workspace-config.md) — workspace-owned templates, Main Cities, chart mappings and scoring methodologies.
- [Administrator Config](administrator-config.md) — users, portability, databases and datasets.
- [Project Structure](project-structure.md) — source/browser layers, database ownership, persistent storage, caches and generated output.
- [Roadmap](roadmap.md) — current limitations and planned work.

## Fast troubleshooting

- A dataset is missing from a selector: verify that the correct workspace is open, its type is correct and processing finished successfully.
- Vendor Comparison is disabled: map every selected Data, Voice and Speech CDR first.
- A chart is empty: open **View filtered dataset** and check datasets, technology, filter values and sample counts.
- A template cannot be saved: use the `Slide: n - Chart: n` validation message to locate the invalid cell.
- A Docker update looks stale: verify the running image digest/tag and recreate the container after pulling.
- A server transfer does not start: confirm destination reachability, URL/port, destination super-admin session and offer status.
