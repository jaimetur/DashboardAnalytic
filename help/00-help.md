# Dashboard Analytic Help

Use this Help centre for detailed workflows, examples and technical rules. For a shorter introduction and deployment quick start, open the **Readme** tab.

## Choose where to start

- New to the product? Read [Product Overview](01-overview.md).
- Comparing results with another tool? Read [Technical Considerations](02-technical-considerations.md).
- Installing the service? Read [Configuration](03-configuration.md) and [Docker Deployment](11-docker-deployment.md).
- Uploading data? Read the [Data Ingestion](05-workspace-management.md#data-ingestion) section in Workspace Management.
- Analysing one dataset? Read [Datasets Analysis](06-datasets-analysis.md).
- Exploring a complete template as a live dashboard or generating its PowerPoint? Read [E2E Dashboards](07-e2e-dashboards.md).
- Generating persistent Reports or Chart Sets? Read [E2E Reporting](08-e2e-reporting.md).
- Authoring templates or managing users and transfers? Read [Administration](10-administration.md), including the [Report Template reference](10-administration.md#report-template-reference).

## Documentation map

1. [Product Overview](01-overview.md) — detailed tour of every module and panel.
2. [Technical Considerations](02-technical-considerations.md) — normalisation, execution semantics, vendor mapping, storage, Dashboard caching and jobs.
3. [Configuration](03-configuration.md) — runtime/rendering variables, storage roots, Docker settings and initial access.
4. [Web Interface](04-web-interface.md) — shared navigation, dialogs, tables and responsive behaviour.
5. [Workspace Management](05-workspace-management.md) — workspaces, data ingestion, processing, previews and mappings.
6. [Datasets Analysis](06-datasets-analysis.md) — interactive single-dataset analysis and exports.
7. [E2E Dashboards](07-e2e-dashboards.md) — saved Dashboards, synchronized filters and slide layouts.
8. [E2E Reporting](08-e2e-reporting.md) — classic Reports, Chart Sets, interactive previews and jobs.
9. [Chart Builder](09-chart-builder.md) — temporary ad-hoc chart construction.
10. [Administration](10-administration.md) — users, complete Report Template authoring reference, portability, databases and datasets.
11. [Docker Deployment](11-docker-deployment.md) — production, development, persistence and upgrades.
12. [Project Structure](12-project-structure.md) — source/browser layers, database ownership, persistent storage, caches and generated output.
13. [Roadmap](13-roadmap.md) — current limitations and planned work.

## Fast troubleshooting

- A dataset is missing from a selector: verify that the correct workspace is open, its type is correct and processing finished successfully.
- Vendor Comparison is disabled: map every selected Data, Voice and Speech CDR first.
- A chart is empty: open **View filtered dataset** and check datasets, technology, filter values and sample counts.
- A template cannot be saved: use the `Slide: n - Chart: n` validation message to locate the invalid cell.
- A Docker update looks stale: verify the running image digest/tag and recreate the container after pulling.
- A server transfer does not start: confirm destination reachability, URL/port, destination super-admin session and offer status.
