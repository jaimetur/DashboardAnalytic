# Product overview

Dashboard Analytic turns processed CDR datasets into interactive KPI analysis, reusable charts and template-driven PowerPoint reports. It is a multi-user application: data and generated output are isolated by workspace, while users and Slides Templates are shared configuration.

## End-to-end workflow

1. Sign in and open a workspace.
2. Upload Data, Voice or Speech CDRs from **Workspace**.
3. Confirm the detected input type and wait for processing to finish.
4. Optionally map Vodafone and Three vendor information.
5. Explore one dataset in **E2E Dashboard**, build an ad-hoc chart in **Chart Builder**, or combine campaigns in **E2E Reporting**.
6. Review background work in **Reports and Charts Jobs**.
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
- Open eligible datasets in E2E Dashboard.
- Stop, retry or delete work.
- Apply, clear and reapply vendor mappings.

Example: upload `NetCheck_CDR_Data_2026_Q2.xlsx`, confirm **CDR-Data**, wait for **Processed**, then use **Show Dashboard** or select it from Reporting.

## E2E Dashboard

E2E Dashboard analyses one processed CDR at a time.

### Dashboard Controls

- Select a processed Data, Voice or Speech CDR.
- Choose one or more numeric KPIs.
- Apply adaptive categorical and date filters.
- Select comparison aggregations supported by the dataset.
- Use **Update Dashboard** to calculate the requested view.
- Open the persisted dataset preview.

### Executive Dashboard

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

## E2E Reporting

E2E Reporting combines processed CDRs and a shared Slides Template.

### Reporting module selector

- **NetCheck CDR Reports** is the active CDR workflow.
- **Smart Orchestrator Logs Reports** reserves the future log-report workflow.

### NetCheck CDR Reports

- Select one or more Data, Voice and Speech CDRs.
- The two newest CDRs of each type are selected initially for Operator Comparison.
- Vendor Comparison keeps one selected CDR per type and requires persisted vendor mapping.
- Choose NSA or SA technology.
- Choose a compatible Slides Template.
- Generate a PowerPoint report or a standalone Chart Set.

### Charts Panel

- Select report-rendered or standalone Chart Sets.
- Open thumbnails in the shared interactive Chart Preview.
- Temporarily change chart type, datasets, KPI, filters, aggregations and legend.
- Open the complete filtered dataset with server-side pagination and column filters.
- Download or delete Chart Sets.
- Administrators can open the Slides Template used by the selected set.

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

### Slides Templates Management

- Create, import, rename, duplicate, export and delete templates.
- Change NSA/SA type.
- Set the default template for each technology.
- Open the editor in a large dialog tied to the selected template.

### Slides Template Editor

- Edit cells in a scrollable grid.
- Validate filter syntax immediately.
- Use searchable assistance and the shared Filter Builder.
- Preview chart data or a generated chart.
- Apply temporary preview values back to the in-memory row with **Update Template**.
- Save atomically; saved cells then clear their change highlighting.

### Export / Import

- Export Config, Slides Templates, accessible workspaces or a Full Environment.
- Select which workspaces belong to a Full Environment package.
- Inspect an import before overwriting configuration or workspaces.
- Transfer authorised content directly to another server.
- Follow package creation, transmission, reception and import progress.
- Recover or delete complete, unimported transfer packages.

### Database Management

- Browse global configuration and active-workspace tables by group.
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
| `user` | Use accessible workspaces, Dashboard, Reporting, Chart Builder and App Logs. |
| `admin` | User operations allowed by policy, Slides Templates, accessible-workspace export/transfer and database administration. |
| `super-admin` | Full account/workspace access management, configuration/full-environment portability and incoming transfer approval. |

For the detailed Workspace/Data Ingestion workflow, continue with [Workspace Management](05-workspace-management.md). For storage rules, calculated fields, filter syntax, reporting semantics and migration behaviour, continue with [Technical considerations](02-technical-considerations.md).
