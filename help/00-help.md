# Dashboard Analytic Help

This help centre covers the Dashboard Analytic workflow: managed source ingestion, E2E KPI analysis, template-backed NetCheck CDR reporting and administration. The navigation panel intentionally lists only documentation maintained for this project.

## What this application does

Dashboard Analytic separates work into named, isolated workspaces and three connected product areas:

- **Workspace** starts with Workspace Management. Create, open, close, rename, duplicate or remove a workspace, then upload NetCheck CDR Data, Voice and Speech workbooks, Smart Orchestrator Logs and operator-specific Multivendor Mappings. Every workspace has independent files, templates and database contents.
- **E2E Dashboard** is the interactive analysis surface for one processed dataset. It provides adaptive filters, KPI summaries, percentile scorecards, CDF/comparison charts and exports of the active dashboard scope.
- **E2E PowerPoint Reporting** produces the standard NSA or SA NetCheck CDR PowerPoint from the three processed CDR domains and selected workspace Slides Templates. A multivendor run uses Vendor values that were mapped and stored on the CDR beforehand.

## Recommended reading order

- **01.** [Configuration](01-configuration-file.md) — set up application access and persistent storage.
- **02.** [Web interface](02-web-interface.md) — understand the Workspace, Dashboard, Reporting, Help and Administration areas.
- **03.** [Data ingestion](03-data-ingestion.md) — upload and process source datasets.
- **04.** [E2E Dashboard](04-e2e-dashboard-analysis.md) — explore interactive KPI analysis.
- **05.** [E2E PowerPoint Reporting](05-e2e-ppt-reporting.md) — generate NetCheck CDR & Smart Orchestrator Logs reports.
- **06.** [Administration](06-admin-panel.md) — manage accounts and review operational activity.
- **07.** [Docker deployment](07-docker-deployment.md) — run the application as a docker container service.
- **08.** [Project structure](08-project-structure.md) — find the project structure.
- **09.** [Roadmap](09-roadmap.md) — review the planned development roadmap.

## Getting help

Start in Workspace when a source file has not yet been processed. A report can only use datasets that have already been uploaded and processed in the open workspace. NetCheck reporting can select one or more processed Data, Voice and Speech CDRs. To use Multivendor, map Vendor values first from the CDR's **Map Vendors** action using available VFUK/3UK mappings; the Reporting scope is enabled only when every selected CDR is mapped. If no workspace is open, open or create one before using ingestion, Dashboard or Reporting. If a file or template is not offered by a selector, verify its processing status, assigned type and default state in Workspace or Administration.
