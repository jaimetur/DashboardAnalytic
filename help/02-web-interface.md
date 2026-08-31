# Web interface

The application follows one operational workflow: upload and process files in Workspace, explore them in the E2E Dashboard, or generate a presentation in E2E PowerPoint Reporting.

## Main areas

| Area | Purpose |
| --- | --- |
| **Workspace** | Manage isolated workspaces, then upload, classify and process their datasets. It is the source-of-truth entry point for analysis and reporting. |
| **E2E Dashboard** | Explore one processed dataset with adaptive filters, KPI summaries, scorecards, CDF/comparison charts and dashboard exports. |
| **E2E PowerPoint Reporting** | Generate standardised NSA or SA NetCheck CDR PowerPoint reports from three processed CDR domains. It also shows the future Smart Orchestrator Logs Reports module. |
| **Administration** | Manage users and templates, inspect the active workspace database and review audit activity; restricted to authorised administrators. |
| **Help** | Opens this documentation in the current application tab with its own navigation panel. |

Workspace, Dashboard and Reporting are shown as application tabs directly above the content panel. Readme, Changelog, Help and (for administrators) Admin share that row on the right; only sign-out remains in the top navigation.

## Workspace

Start in **Workspaces Management**. The selector defaults to the most recently opened workspace. Use **Open** or **Close** to control the active workspace; **Manage Workspace** creates, renames, duplicates or removes workspaces. A closed workspace disables Dashboard and Reporting and hides ingestion/queue operations. Each workspace stores its own database, files and editable Slides Templates.

With a workspace open, use **Upload** to add a supported source file. Workspace accepts NetCheck CDR Data, Voice and Speech workbooks, Smart Orchestrator Logs and separate VFUK/3UK Multivendor Mappings. It proposes a type from the filename; confirm or correct it before processing. When ready mappings already exist and a file is classified as a CDR, that file also shows optional VFUK and 3UK mapping selectors. The latest ready mapping of each type is proposed; choose **No Map Vendor Column** to skip it, or select only one mapping to enrich only that operator. When several files are selected, each has its own selectors in the review panel. The **Data Processing** queue can be narrowed by input type, with **All Types** selected initially and unavailable types disabled.

Once a dataset is processed, **Preview** opens a read-only sample in a new tab. It supports a configurable row limit, free-text row/column matching and Excel-style value menus on table headers; CDR previews also provide multi-select Operator, Vendor, RAT, Session Type and Call Status filters. Mapping previews provide GCID/Vendor filtering and highlight those fields. CDR rows also expose **Show Dashboard**. When mappings are available, an unmapped CDR exposes **Map Vendors**; a mapped CDR exposes **Clear Vendors** for a clean remap. Check that the status is **Processed** before moving on: datasets still processing or showing an error are not valid report inputs.

## E2E Dashboard

Select a processed CDR dataset, then use the available controls to narrow the view by the dimensions present in that data. The dashboard exposes KPI-like numeric metrics only; coordinate fields, identifiers and technical metadata are excluded. Adaptive filters support compact multi-selection, date ranges and available CDR values. **Preview Dataset** opens the same persisted-data preview as Workspace. KPI tables and charts always reflect the active filters. Confirm the dataset, filters and aggregation before using a Word or PowerPoint export action.

## E2E PowerPoint Reporting

Open **NetCheck CDR Reports** to create a PowerPoint report. The form requires three processed workspace datasets: one **Data**, one **Voice** and one **Speech** CDR. Select NSA or SA, then select the report scope.

Choose the workspace Slides Templates that define the report. The default template is selected initially, but any stored template of the selected technology can be used for that report. For **Single-vendor**, no further mapping is required. **Multivendor** is available only when all selected Data, Voice and Speech CDRs already have persisted Vendor values; mappings are completed in Workspace rather than Reporting. During the multivendor render, `Operator` grouping dimensions become `Vendor`, `Operator` legends become `Campaign`, and slide/chart titles use `Vendor`; `Operator` filters still use the original CDR Operator field. The generated report uses the selected template, replaces its example charts with calculations from the persisted CDR rows and leaves analyst commentary areas blank. When generation completes, the timestamp-named report downloads and the progress dialog closes automatically.

**Smart Orchestrator Logs Reports** is visible as a future module but is not implemented yet.

## Help navigation

The Help tab keeps the user in the current application tab. `00. Help Home 🏠` is the first item in the left navigation and the other articles are numbered from their filenames in the same order. Only documentation relevant to Dashboard Analytic is listed.
