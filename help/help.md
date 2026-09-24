<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="Dashboard Analytic logo" width="320">
</p>

# Dashboard Analytic Help

Use this Help centre for detailed workflows, examples and technical rules. For a shorter introduction and deployment quick start, open the **Readme** tab.

Help Navigation groups chapters under General, Main Modules, Administrative Modules and Reference. Chapters outside your access are omitted.

## Choose where to start

- New to the product? Read [Product Overview](overview.md).
- Comparing results with another tool? Read [Technical Considerations](technical-considerations.md).
- Installing the service? Read [Deployment Configuration](configuration.md) and [Docker Deployment](docker-deployment.md).
- Uploading data? Read the [Data Ingestion](workspace-management.md#data-ingestion) section in Workspace Management.
- Analysing one dataset? Read [Datasets Analysis](datasets-analysis.md).
- Exploring a complete template as a live dashboard or generating its PowerPoint? Read [E2E Dashboards](e2e-dashboards.md).
- Generating persistent Reports or Chart Sets? Read [E2E Reporting](e2e-reporting.md).
- Building ad-hoc SQL queries with guided controls? Read [Query Builder](query-builder.md).
- Authoring templates? Read [Workspace Config](workspace-config.md), including the [Report Template reference](workspace-config.md#report-template-reference).
- Managing users and transfers? Read [Administrator Config](administrator-config.md).
- Changing application-wide runtime settings? Read [Application Config](app-config.md).
- Managing templates and chart mappings for a workspace? Read [Workspace Config](workspace-config.md).
- Reviewing application and workspace activity? Read [App Logs](app-logs.md).

## Documentation map

- [Product Overview](overview.md) — detailed tour of every module and panel.
- [Technical Considerations](technical-considerations.md) — normalisation, execution semantics, vendor mapping, storage, Dashboard caching and jobs.
- [Deployment Configuration](configuration.md) — runtime/rendering variables, storage roots, Docker settings and initial access.
- [Docker Deployment](docker-deployment.md) — production, development, persistence and upgrades.
- [Web Interfaces](web-interface.md) — shared navigation, dialogs, tables and responsive behaviour.
- [Workspace Management](workspace-management.md) — workspaces, data ingestion, processing, previews and mappings.
- [Datasets Analysis](datasets-analysis.md) — interactive single-dataset analysis and exports.
- [E2E Dashboards](e2e-dashboards.md) — saved Dashboards, synchronized filters and slide layouts.
- [E2E Reporting](e2e-reporting.md) — classic Reports, Chart Sets, interactive previews and jobs.
- [Chart Builder](chart-builder.md) — temporary ad-hoc chart construction.
- [Query Builder](query-builder.md) — guided query design, SQL editing, execution and saved queries.
- [App Logs](app-logs.md) — workspace events and live server output.
- [Application Config](app-config.md) — application-wide runtime settings and their effect.
- [Workspace Config](workspace-config.md) — workspace-owned Report Templates, Operator Mappings and Vendor Mappings.
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
