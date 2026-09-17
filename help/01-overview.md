# Product overview

Dashboard Analytic turns processed CDR datasets into interactive KPI analysis, reusable charts and template-driven PowerPoint reports. It is a multi-user application: datasets, generated output, Auto-calculated Fields and Report Templates are isolated by workspace, while users and access permissions are shared configuration.

## End-to-end workflow

1. Sign in and open a workspace.
2. Upload Data, Voice or Speech CDRs from **Workspace**.
3. Confirm the detected input type and wait for processing to finish.
4. Optionally map Vodafone and Three vendor information.
5. Create or open a saved **E2E Dashboard** to analyse a complete template interactively, reuse prepared selections and generate its PowerPoint. Use **Datasets Analysis** or **Chart Builder** for focused exploration, or **E2E Reporting** for the classic report and Chart Set workflow.
6. Follow Dashboard preparation and generation in the floating task cards, **PowerPoint Generation Jobs** and **Reports and Charts Jobs**.
7. Use **App Logs** for traceability and **Admin** for shared configuration.

## Header and navigation

The header is available throughout the authenticated application.

- **Workspace badge** shows the active workspace and its current disk usage.
- **Workspace selector** switches directly to another accessible workspace.
- **Username button** opens the password-change dialog.
- **Readme** is the default tab after login.
- **Changelog** shows release history.
- **Help** opens this detailed guide.
- **App Logs** opens operational events for the active workspace.
- **Admin** is visible to administrators and super-admins.

## Background tasks and floating cards

Long operations continue while the user navigates between modules or signs out. This includes ingestion and mapping, Auto-calculated Field materialization, combined-table recreation, workspace duplication/deletion/cache clearing, Dashboard preparation and model warming, Report and Chart Set generation, Dashboard PowerPoint generation, backup, import, export and server transfer.

Floating cards group live tasks by execution context and keep their label, detail, percentage, elapsed time and progress bar visible from any application page:

- **Yellow — Active workspace**: work attached to the workspace currently open in the browser.
- **Blue — Other workspace**: work that continues for a different workspace after the user switches away from it.
- **Red — System tasks**: deployment-wide work such as portable-package and server-transfer operations.

Dashboard cards also group preparation and chart-model work under the Dashboard name and distinguish the active item from its queued position. An **Interrupt task** action appears when the job supports cancellation. Cards can be minimized without interrupting their tasks, refresh automatically, and retain a completed task briefly so its final state is visible before the card disappears. Persistent generation jobs remain available in their module table after the floating notification closes.

## Workspace

Workspace is the entry point for data and storage management.

### Workspaces Management

- Create, open, close, rename, duplicate and delete workspaces.
- Review the current size of each workspace.
- Control workspace access when authorised.
- Keep databases, uploaded files and generated outputs isolated.

### Data Ingestion

- Upload `CSV`, `XLS`, `XLSX` and `XLSM` files.
- Review the proposed type for every file in a batch.
- Import CDR-Data, CDR-Voice, CDR-Speech, Smart Orchestrator Logs, VFUK mappings, 3UK mappings or generic datasets.
- Optionally apply ready VFUK/3UK mappings while a CDR is processed.

### Queue and Status

- Follow processing progress.
- Filter the queue by dataset type.
- Preview processed rows with searchable, Excel-style column filters.
- Open eligible datasets in Datasets Analysis.
- Stop, retry or delete work.
- Apply, clear and reapply vendor mappings.

### Auto-calculated Fields and combined CDR tables

- Create, edit, duplicate, delete, import and export Auto-calculated Fields from the Workspace panel.
- A field is applied only to the CDR types selected in **Available for**.
- Saving, importing or rematerializing fields starts a background job. The Materialization status panel shows its percentage and completion state.
- Existing combined `CDR-Data`, `CDR-Voice` and `CDR-Speech` tables appear at the bottom of Datasets. Preview them with the same filters as individual CDRs.
- Use the circular **Recreate** action when a combined table needs rebuilding. It restores missing individual persisted rows from their source file when possible, then verifies contributed and total row counts.

Example: upload `NetCheck_CDR_Data_2026_Q2.xlsx`, confirm **CDR-Data**, wait for **Processed**, then use **Show Analysis** or select it from Reporting.

## Datasets Analysis

Datasets Analysis analyses one processed CDR at a time.

### Analysis Controls

- Select a processed Data, Voice or Speech CDR.
- Choose one or more numeric KPIs.
- Apply adaptive categorical and date filters.
- Select comparison aggregations supported by the dataset.
- Use **Update Analysis** to calculate the requested view.
- Open the persisted dataset preview.

### Dataset Summary

- Shows the active dataset and filtered sample count.
- Presents headline KPI cards and percentile scorecards.
- Keeps the analytical context visible before export.

### Charts and Scorecards

- CDF curves show KPI distributions.
- Group benchmarks compare aggregation values.
- Metric cards summarise each selected KPI.

### Processed Metrics

- Shows the filtered and aggregated records behind the dashboard.
- Supports Word and PowerPoint exports of the active analysis.

## E2E Dashboards

E2E Dashboards is the main analysis module and the complete template-driven workflow behind Dashboard Analytic. A saved Dashboard binds a name and NR Mode to a workspace Report Template, filters, hidden fields and slide comments. Scope, selected Data/Voice/Speech CDRs and dates define the current Dataset Universe and remain session state rather than persisted filters. The definition can be opened repeatedly, duplicated, exported or moved with its workspace without copying source rows into it.

### Manage Dashboards

- Create, open, rename, duplicate, export, import, close and delete workspace Dashboard definitions.
- Choose NSA or SA before selecting a compatible Report Template.
- Open the definition editor or enter the prepared viewer directly from the Dashboard library.
- Preserve the last open Dashboard and page position within the browser session.

### Dashboard Datasets & Filters

- Build one **Dataset Universe** from any compatible Data, Voice and Speech CDRs, then compare operators or persisted vendor mappings.
- Use automatic date bounds and synchronized default filters for Market, Operator, Vendor, Region, City, Campaign, RAT, Session Type and Call Status.
- Resolve Region, City, RAT and other known fields through ordered source-column aliases, with the supported priority visible in a tooltip.
- Add any selected-CDR column or applicable Auto-calculated Field as an extra filter.
- Apply changed filters, save them as the Dashboard default, reload the saved filters or clear them. Scope, CDRs and dates prepare automatically when viewing or exporting; pending filter changes offer Apply, Discard, Save or Cancel.

### Preparation and reuse

The module prepares a **Filtered Universe** once and reuses it across every template chart. Its selection metadata contains counts, facets and reproducible SQL predicates; chart queries run directly against the combined CDR tables. Reusable preview manifests and versioned Canvas models avoid rebuilding unchanged work after reopening a Dashboard or restarting the application. Preparation starts only when a user opens, refreshes or exports a Dashboard; listing, saving, editing and opening a workspace never enqueue Dashboard warm-up work. One global gate permits only one explicitly requested Dashboard dataset-preparation phase at a time. Opening a workspace removes cache artifacts written by older application or cache-format versions.

Status cards distinguish data loading, queued data, chart rendering, queued charts, Ready, missing charts and failures. The floating background-task card shows the same work while users move between modules.

### View Dashboard

- Convert every template Slide into a navigable 16:9 screen and place charts using its stored Layout geometry.
- Navigate slides, expand a chart, zoom and pan its Canvas model, refresh it and move between charts without regenerating the complete Dashboard.
- Open the exact chart-filtered rows with server-side pages, Excel-style column filters and CSV download.
- Edit slide comments, run timed Presentation mode and reopen synchronized filters from a floating panel.
- Open Auto-calculated Fields or the exact template row when the current role permits it.

### Generate PPT and review results

**Generate PPT** uses the exact applied definition and continues as a background job. Completed jobs retain their CDRs, dates, scope, filter snapshot, comments, PPTX, PNGs, tooltips and Canvas models under `output/dashboards`. **PowerPoint Generation Jobs** supports download, chart access, stop, retry, relaunch and deletion. **Charts Panel** filters completed jobs and reopens their charts in the same expanded viewer, including the historical chart dataset.

The operational guide is [E2E Dashboards](07-e2e-dashboards.md). Template creation, columns, structural slides, supported chart types, filters, aggregations, legends, layouts and colours are documented once in [Administration → Report Template reference](10-administration.md#report-template-reference).

## E2E Reporting

E2E Reporting combines processed CDRs and a Report Template from the active workspace.

### Reporting module selector

- **NetCheck CDR Reports** is the active CDR workflow.
- **Smart Orchestrator Logs Reports** reserves the future log-report workflow.

### NetCheck CDR Reports

- Select one or more Data, Voice and Speech CDRs.
- The two newest CDRs of each type are selected initially for Operator Comparison.
- Vendor Comparison keeps one selected CDR per type and requires persisted vendor mapping.
- Choose NSA or SA technology.
- Choose a compatible Report Template.
- Generate a PowerPoint report or a standalone Chart Set.

### Charts Panel

- Select report-rendered or standalone Chart Sets.
- Open thumbnails in the shared interactive Chart Preview.
- Temporarily change chart type, datasets, KPI, filters, aggregations and legend.
- Open the complete filtered dataset with server-side pagination and column filters.
- Download or delete Chart Sets.
- Administrators can open the Report Template used by the selected set.

### Reports and Charts Jobs

- Shows both job types in one chronologically ordered table.
- Uses **Tech** for NSA/SA and **Type** for Report/Charts.
- Keeps the actions appropriate to each job: open, download, stop, retry, relaunch or delete.
- Provides separate bulk deletion for Reports and Chart Sets.
- Persists both job types in the workspace `generated_jobs` table.

## Chart Builder

Chart Builder creates temporary, ad-hoc charts without generating a report.

- Choose the CDR Type first: Data, Voice or Speech.
- Select one or more processed datasets of that type.
- Configure Chart Title, Chart Type, KPI, Filters, Rows, Columns, Legend and Legend Position.
- Use searchable single-select and ordered multi-select controls.
- Inspect the parsed filter and aggregation expressions.
- Regenerate the preview automatically as the definition changes.

Example:

```text
CDR Type: Data
Datasets: 2026-Q1 and 2026-Q2
Chart Type: CDF Line
KPI: Mean_Data_Rate
Filters: Test_Result = Completed; Operator IN (VF, 3, EE)
Rows: Operator
Columns: Campaign
Legend: Campaign
```

## App Logs

App Logs presents meaningful user and system events rather than every UI click.

- Filter by **User**, **Executed by**, date, type and action.
- User names are matched case-insensitively and displayed in lowercase.
- **User** identifies the person associated with the workflow.
- **Executed by** identifies who performed the step; automatic steps use `system`.
- Login details state whether authentication succeeded or failed.
- The page refreshes automatically every five seconds and also provides manual Refresh.

## Admin

Admin is available to `admin` and `super-admin` roles, with permission-sensitive actions.

### User management

- Create, rename, enable, disable and delete users.
- Reset passwords.
- Assign roles and workspace access where permitted.

### Report Templates Management

- Create, import, rename, duplicate, export and delete templates in the active workspace.
- Change NSA/SA type.
- Set the default template for each technology.
- Open the editor in a large dialog tied to the selected template.

Templates belong to their workspace and live in its `report_templates` database table. A new workspace starts without templates; portable operations represent selected templates as CSV files inside their ZIP package.

### Report Template Editor

- Edit cells in a scrollable grid.
- Validate filter syntax immediately.
- Use searchable assistance and the shared Filter Builder.
- Preview chart data or a generated chart.
- Apply temporary preview values back to the in-memory row with **Update Template**.
- Save atomically; saved cells then clear their change highlighting.

The complete authoring specification, examples and supported chart catalogue are in [Administration → Report Template reference](10-administration.md#report-template-reference).

### Import / Export / Transfer

- Export the active workspace's Report Templates, Auto-calculated Fields, accessible workspaces or a Full Environment.
- Select which workspaces belong to a Full Environment package.
- Inspect an import before overwriting configuration or workspaces.
- Template and Auto-calculated Field packages select the source workspace automatically when a workspace with the same name exists; additional accessible workspaces can also be selected.
- Transfer authorised content directly to another server.
- Follow package creation, transmission, reception and import progress.
- Recover or delete complete, unimported transfer packages.

### Database Management

- Use **Backup Protection** for on-demand or scheduled ZIP backups. It offers independent Application database, Workspace Database, Report Templates, Auto-calculated Fields, Input and Output selections, then restores detected granular components after an overwrite confirmation.
- Use **Database Viewer** to browse grouped application-configuration, active-workspace and combined-CDR tables.
- Filter complete tables with Excel-style column menus.
- Edit or delete individual rows.
- Clean orphaned materialised dataset rows.
- Inspect the unified **Generated jobs** table for Reports and Chart Sets.

### Datasets Management

- Review stored dataset identity, type, ownership and processing state.
- Rename datasets without re-uploading their source files.

## Roles at a glance

| Role | Typical permissions |
| --- | --- |
| `user` | Use accessible workspaces, Datasets Analysis, E2E Dashboards, Reporting, Chart Builder and App Logs. |
| `admin` | User operations allowed by policy, Report Templates, accessible-workspace export/transfer and database administration. |
| `super-admin` | Full account/workspace access management, configuration/full-environment portability and incoming transfer approval. |

For the detailed Workspace/Data Ingestion workflow, continue with [Workspace Management](05-workspace-management.md). For storage rules, calculated fields, filter syntax, reporting semantics and migration behaviour, continue with [Technical considerations](02-technical-considerations.md).
