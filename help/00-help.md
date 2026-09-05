# Dashboard Analytic Help

Use this Help centre for detailed workflows, examples and technical rules. For a shorter introduction and deployment quick start, open the **Readme** tab.

## Choose where to start

- New to the product? Read [Product Overview](01-overview.md).
- Comparing results with another tool? Read [Technical Considerations](02-technical-considerations.md).
- Installing the service? Read [Configuration](03-configuration.md) and [Docker Deployment](10-docker-deployment.md).
- Uploading data? Read the [Data Ingestion](05-workspace-management.md#data-ingestion) section in Workspace Management.
- Building a dashboard? Read [E2E Dashboard](06-e2e-dashboard.md).
- Generating charts or PowerPoint? Read [E2E Reporting](07-e2e-reporting.md).
- Managing users, templates or transfers? Read [Administration](09-administration.md).

## Documentation map

1. [Product Overview](01-overview.md) — detailed tour of every module and panel.
2. [Technical Considerations](02-technical-considerations.md) — normalisation, filters, aggregation, legends, vendor mapping, storage and performance.
3. [Configuration](03-configuration.md) — runtime variables, storage roots and initial access.
4. [Web Interface](04-web-interface.md) — shared navigation, dialogs, tables and responsive behaviour.
5. [Workspace Management](05-workspace-management.md) — workspaces, data ingestion, processing, previews and mappings.
6. [E2E Dashboard](06-e2e-dashboard.md) — interactive single-dataset analysis and exports.
7. [E2E Reporting](07-e2e-reporting.md) — reports, Chart Sets, templates, chart recipes and jobs.
8. [Chart Builder](08-chart-builder.md) — temporary ad-hoc chart construction.
9. [Administration](09-administration.md) — users, templates, portability, databases and datasets.
10. [Docker Deployment](10-docker-deployment.md) — production, development, persistence and upgrades.
11. [Project Structure](11-project-structure.md) — source, storage and runtime components.
12. [Roadmap](12-roadmap.md) — current limitations and planned work.

## Fast troubleshooting

- A dataset is missing from a selector: verify that the correct workspace is open, its type is correct and processing finished successfully.
- Vendor Comparison is disabled: map every selected Data, Voice and Speech CDR first.
- A chart is empty: open **View filtered dataset** and check datasets, technology, filter values and sample counts.
- A template cannot be saved: use the `Slide: n - Chart: n` validation message to locate the invalid cell.
- A Docker update looks stale: verify the running image digest/tag and recreate the container after pulling.
- A server transfer does not start: confirm destination reachability, URL/port, destination super-admin session and offer status.
