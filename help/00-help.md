# Dashboard Analytic Help

This help centre covers the Dashboard Analytic workflow: managed source ingestion, E2E KPI analysis, template-backed NetCheck CDR reporting and administration. The navigation panel intentionally lists only documentation maintained for this project.

## What this application does

Dashboard Analytic separates the work into three connected product areas:

- **Workspace** is the controlled entry point for NetCheck CDR Data, Voice and Speech workbooks, Smart Orchestrator Logs and operator-specific Multivendor Mappings. It proposes a file type from the name, allows an analyst to correct it, then stores the processed data for later use.
- **E2E Bench Dashboard** is the interactive analysis surface for one processed dataset. It provides adaptive filters, KPI summaries, percentile scorecards, CDF/comparison charts and exports of the active dashboard scope.
- **E2E Bench Reporting** produces the standard NSA or SA NetCheck CDR PowerPoint from the three processed CDR domains. A multivendor run additionally uses one VFUK mapping for Vodafone UK and one 3UK mapping for Three UK.

## Recommended reading order

1. [Configuration](01-configuration-file.md) — set up application access and persistent storage.
2. [Web interface](02-web-interface.md) — understand the Workspace, Dashboard, Reporting, Help and Administration areas.
3. [Data ingestion](03-data-ingestion.md) — upload and process source datasets.
4. [KPI analysis](04-kpi-analysis.md) — explore the E2E Bench Dashboard.
5. [PowerPoint reporting](05-powerpoint-reporting.md) — generate NetCheck CDR reports.
6. [Administration](06-admin-panel.md) — manage accounts and review operational activity.
7. [Docker deployment](07-docker-deployment.md) — run the application as a service.
8. [Project structure](08-project-structure.md) and [roadmap](09-roadmap.md) — find the implementation areas and planned scope.

## Getting help

Start in Workspace when a source file has not yet been processed. A report can only use datasets that have already been uploaded and processed in the workspace. For NetCheck reporting, select one processed Data CDR, one Voice CDR and one Speech CDR; choose Multivendor only when both the VFUK Vodafone and 3UK Three mapping files are also available. If a file is not offered by a selector, first verify its processing status and its assigned type in Workspace.
