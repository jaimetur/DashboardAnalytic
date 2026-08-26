# Web interface

The application follows one operational workflow: upload and process files in Workspace, explore them in the E2E Dashboard, or generate a presentation in E2E PowerPoint Reporting.

## Main areas

| Area | Purpose |
| --- | --- |
| **Workspace** | Upload, classify and process datasets. It is the source-of-truth entry point for analysis and reporting. |
| **E2E Dashboard** | Explore one processed dataset with adaptive filters, KPI summaries, scorecards, CDF/comparison charts and dashboard exports. |
| **E2E PowerPoint Reporting** | Generate standardised NSA or SA NetCheck CDR PowerPoint reports from three processed CDR domains. It also shows the future Smart Orchestrator Logs Reports module. |
| **Administration** | Manage users, inspect stored datasets and review audit activity; restricted to authorised administrators. |
| **Help** | Opens this documentation in the current application tab with its own navigation panel. |

Workspace, Dashboard and Reporting are shown as application tabs directly above the content panel. Readme, Changelog, Help and (for administrators) Admin share that row on the right; only sign-out remains in the top navigation.

## Workspace

Use **Upload** to add a supported source file. Workspace accepts NetCheck CDR Data, Voice and Speech workbooks, Smart Orchestrator Logs and VFUK/3UK Multivendor Mappings. It proposes a type from the filename; confirm or correct it before processing. When several files are selected, each has its own type selector in a review panel. The **Data Processing** queue can be narrowed by input type, with **All Types** selected initially. Once a dataset is processed, **View** shows a read-only row preview; CDR Data, Voice and Speech rows also expose **Show Dashboard** to open their KPI analysis. Check that the status is **Processed** before moving on: datasets still processing or showing an error are not valid report inputs.

## E2E Dashboard

Select a processed dataset, then use the available controls to narrow the view by the dimensions present in that data. The dashboard exposes available numeric metrics, global and per-metric KPI cards, percentile scorecards, CDF/comparison views and filtered records. KPI tables and charts always reflect the active filters. Confirm the dataset, filters and aggregation before using a Word or PowerPoint export action.

## E2E PowerPoint Reporting

Open **NetCheck CDR Reports** to create a PowerPoint report. The form requires three processed workspace datasets: one **Data**, one **Voice** and one **Speech** CDR. Select NSA or SA, then select the report scope.

For **Single-vendor**, no mapping is requested. For **Multivendor**, separate **VFUK Vodafone UK** and **3UK Three UK** mapping selectors appear and both inputs are mandatory. The generated report uses the selected template, replaces its example charts with calculations from the persisted CDR rows and leaves analyst commentary areas blank. When generation completes, the report downloads and the progress dialog closes automatically.

**Smart Orchestrator Logs Reports** is visible as a future module but is not implemented yet.

## Help navigation

The Help tab keeps the user in the current application tab. `0. 🏠 Help Home` is the first item in the left navigation and the other articles are numbered in the same order. Only documentation relevant to Dashboard Analytic is listed.
