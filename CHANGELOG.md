# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.0
### Release Date: 2026-08-31
#### 🌟 New Features:
- Added modular Workspace, Dashboard and PowerPoint Reporting areas, including Smart Orchestrator Logs reports.
- Redesigned the web UI with dedicated Workspace, Dashboard, Reporting and Admin panels.
- Added CDR ingestion for Data, Voice and Speech with VFUK/3UK vendor mapping and review queues.
- Added template-driven NSA/SA and multivendor PowerPoint reports with persistent job history.
- Added shared Slides Templates Management and an editor with import, defaults, duplication, deletion and export.
- Added multi-workspace lifecycle management (create, open, close, rename, duplicate and remove).
- Added Admin Database Management with table browsing, row editing/deletion and Excel-style filters.
- Added Admin Import/Export ZIP packages for configuration, templates, workspaces and full environments.
- Added self-service password changes from the header User badge.
- Added processed-dataset preview and direct Preview/Show Dashboard actions from workspace and Admin.
- Added Generated Reports Jobs with Download and Delete actions, progress tracking and report metadata.
- Added configurable Data, Voice and Speech CDR comparison reports, including multiple campaigns and multivendor output.

#### 🚀 Enhancements:
- Added root-level `storage-paths.conf` and `APP_CONFIG_DIR`, `APP_DATA_DIR` and `APP_ASSETS_DIR` overrides.
- Made templates drive report titles, charts, filters, aggregations, legends and layout; added `Legend Position` and renamed aggregation columns.
- Grouped and ordered multi-chart slides in the editor while preserving the complete CSV format on save.
- Optimised repeated CDR reports with shared materialised tables and column selection based on the report.
- Improved Dashboard and preview performance, adaptive filters, vendor persistence and large-dataset handling.
- Added safe dataset renaming and synchronised source paths and references.
- Moved templates to `config/slides-templates/`, workspace databases and reports to their workspace directories, and the registry to `data/workspaces/`.
- Made imports and exports disk-backed background jobs with progress, preflight warnings and overwrite confirmation for large packages.
- Added generated-report metadata (template, type, vendor mode, datasets and user), local server dates and compact icon actions.
- Improved PowerPoint chart readability, hierarchical grouping, CDF campaign styling and legend placement.
- Added cleanup of orphaned combined-CDR rows after dataset deletion or from Database Management.
- Added Excel-like preview filtering by column values, plus pre-filters for Operator, Vendor, RAT, Session Type and Call Status.
- Added colour-coded Source Sheet, Vendor and GCID fields in dataset previews.
- Added Slides Templates Editor cell assistance that parses the current value, contextual help, searchable selectors, row insertion and multi-chart slide grouping.
- Added reusable blank PowerPoint layouts and CSV-defined slide/chart templates for report generation.
- Added persistent background processing for imports, report generation and large ZIP transfers, independent of the active session.
- Added alternating report-job rows, compact icon actions and server-local report dates.

#### 🐛 Bug fixes:
- Preserved chart-definition fields during template normalisation, sorting and visual merging.
- Fixed templates defaults, renames, deletion protection, editor selection and report placeholder generation.
- Fixed ingestion and mapping for duplicate headers, alternate encodings, Cell ID variants and vendor fields.
- Kept CDR datasets available after failed mappings and recovered previously failed imports.
- Fixed queue ownership and background processing across workspace close and logout.
- Preserved upload dates while tracking updates and latest-dataset selection.
- Fixed Dashboard filter restoration, cache refreshes, empty states and mobile document overflow.
- Fixed Docker packaging so the master PowerPoint template is included in deployed images.
- Fixed template migration and editor normalisation so KPI, chart type, filters, aggregations, legends and layout values are retained.
- Fixed report generation for missing sources, empty tables, duplicate columns, mixed encodings and legacy dataset metadata.
- Fixed multi-level grouping so child campaign bars remain nested under one operator label.
- Fixed report-job filenames, output discovery and historical-job loading after migration to `output/reports`.
- Fixed Admin loading when no default templates or workspace database is present.
- Fixed host-specific absolute storage paths in the checked-in configuration from breaking CI or deployments where that filesystem root is unavailable.
- Standardised timestamp persistence and display on the server's local timezone across dataset queues, profiles, logs, users, workspaces and report jobs.
- Configured Docker timezone handling through `TZ` (default `Europe/Madrid`) so NAS timestamps match the intended local time.
- Stopped creating per-workspace `exports/` directories; report and dashboard exports now use `output/reports/`, with automatic migration of existing files.

#### 📚 Documentation:
- Reworked the Help, README and configuration documentation for the current workspace, template, reporting and transfer workflows.

#### 🔎 Summary vs v0.1.0:
- v0.1.0 provided the initial single-workspace KPI dashboard and basic file ingestion; v0.2.0 adds independent multi-workspace storage and lifecycle management.
- Reporting evolved from basic exports into templates-driven NSA/SA, campaign-comparison and multivendor PowerPoint jobs with persistent history.
- Administration expanded from user management into template, dataset, database and environment Import/Export management.
- Preview, filtering, caching, background processing and large-file transfers were substantially improved for operational datasets.

---

## Release: v0.1.0
### Release Date: 2026-07-14

#### 🌟 New Features:
- Initial Dashboard Analytic MVP for KPI analytics
- FastAPI multi-user web interface
- CSV/XLSX ingestion, KPI scoring, CDF chart, and report exports
- Docker and GitHub Actions setup
- Added automatic CDR workbook processing for `.xlsm`, including multi-sheet operator imports
- Added cached dataset profiles with status, progress, retry, and deduplication by source file
- Added a global processing overlay for uploads, retries, dashboard updates, and exports
- Added app branding assets, favicon support, and header user badges by role
- Expanded the admin `Identity` panel with inline edit, toggle active, and delete actions
- Added PowerPoint export for the full `Visual Analytics` dashboard state

#### 🚀 Enhancements:
- Redesigned the dashboard with a queue table, right-side filters, and collapsible panels
- Moved workspace loading to cached metadata and delayed full analysis until requested
- Refreshed the login screen and added asset versioning for CSS and JS reloads
- Cached dashboard analyses to avoid reloading the dataset on repeated page refreshes
- Renamed the ingestion panels to `Data Ingestion` and `Data Processing Queue`
- Updated production Docker compose to pull published Docker Hub images
- Added login hero logo placement and refined login spacing
- Replaced the browser delete confirm with a styled confirmation modal
- Added multi-file upload with chunked file writes for large datasets
- Updated the queue to refresh progress live without page reloads
- Switched the upload file picker copy to English labels
- Added finer-grained dataset processing progress updates for large files
- Refined the workspace selector layout and queue action button styling
- Renamed the dataset summary panel to `Selected Dataset`
- Added multi-KPI dashboard rendering from the adaptive filters panel
- Moved workspace queries to materialized dataset tables in SQLite
- Added a workspace logs panel with `Info` and `Error` filtering
- Renamed `Data Processing Queue` to `Data Processing`
- Expanded the executive dashboard with global KPIs and per-metric KPI cards
- Added date-range filtering based on `Call Start Time`
- Added `City` filters and multi-select adaptive filters across the workspace
- Added per-chart aggregation overrides for individual comparison charts
- Persisted editable `Workspace` and `Admin` form state in browser storage
- Restored the last opened workspace dataset automatically on return
- Persisted collapse state for workspace and admin panels
- Replaced native multi-select boxes with dropdown multi-select controls and `Select All / None`
- Refined executive metric cards into visual subpanels grouped inside `Executive Dashboard`
- Improved dataset kind detection for `CDR-Speech` and `CDR-Data`
- Reduced PowerPoint export time by reusing cached export files and condensing metric output into fewer slides
- Added dataset size visibility in the `Data Processing` queue with MB labels
- Accelerated dashboard refreshes on large datasets by reducing analysis query columns and indexing materialized filter dimensions

#### 🐛 Bug fixes:
- Fixed default access visibility to reflect active users with default passwords only
- Prevented removing, deactivating, or demoting the last active admin user
- Fixed embedded document images to resolve project `static` asset paths
- Fixed empty-state body copy alignment in the workspace panels
- Fixed dataset selector filtering so all datasets show when no type filter is set
- Fixed the dataset picker to react immediately when `Input Type` changes
- Fixed the upload file input overlay so `Upload and process` submits directly
- Fixed failed processing caused by duplicate column names like `Campaign/campaign`
- Fixed dashboard fallback for legacy `ready` datasets without materialized tables
- Fixed workspace dataset selection to exclude non-ready datasets
- Fixed queue rows to show the dataset `last_error` directly in the workspace
- Fixed date filtering for datasets using spaced headers like `Call Start Time`
- Fixed the dashboard global aggregation selector to stay independent from per-chart overrides
- Fixed lowercase CSV dimensions like `operator` and `region` so chart aggregations work
- Fixed grouped percentiles to fall back gracefully when the chosen comparison has no usable grouped rows
- Fixed `Workspace -> Open` so the clicked dataset stays authoritative even when a stale `input_kind` is present
- Fixed global CDF comparison updates to apply on the first dashboard refresh
- Fixed `Global CDF Comparison` and `Global Aggregation` to persist their last selected values across dashboard returns
- Fixed dashboard relaunch and dataset reopen flows so persisted global CDF and aggregation selections are restored even when `/dashboard` loads with only `dataset_id`
- Fixed legacy materialized dashboard tables to stop rebuilding on every refresh when structural columns only differ by case
- Refined normalized `Technology Primary` for data datasets to prioritize `RAT` and stop deriving it from `PCell_RAT_Timeline`
- Renamed the dashboard-facing `Technology Primary` label to `Technology` while keeping the normalized field key stable
- Added automatic stale-dataset normalization refresh on dashboard open so cached filter options and materialized rows pick up normalization rule changes
- Reworked stale-dataset normalization refresh to migrate cached technology values from the materialized table instead of rebuilding giant datasets during dashboard open
- Optimized large-dashboard CDF rendering by increasing chart sample density and rebuilding grouped comparisons from the actual filtered series so multi-operator CDF views keep all visible curves
- Rebalanced CDF payload size with an adaptive per-chart point budget so giant dashboards open quickly again even when several metrics and comparison curves are rendered together
- Fixed dashboard state persistence from being overwritten by bare `dataset_id + load=1` opens, restoring reliable persistence for `Global CDF Comparison` and `Global Aggregation`
- Fixed app relaunch persistence for `Global CDF Comparison` and `Global Aggregation` when dashboard bootstrap URLs explicitly carried the default `all` values
- Fixed persisted global dashboard selectors to restore correctly even when the incoming dashboard URL already contains `aggregation=all` or `cdf_grouping=all`
- Fixed restored global dashboard selectors to push their persisted values back into the dashboard URL so child CDF and bar charts render with the same global settings after app relaunch
- Changed `Adaptive Filters` persistence to be dataset-specific so metrics, dates and dimension filters restore independently for each dataset when switching back and forth
- Fixed dashboard dataset switching to load the target dataset with its persisted filters before the first render, preventing default filters from flashing and being resubmitted accidentally
- Fixed `Workspace -> Open` and live queue `Open` actions to enter `/dashboard` through the dataset-specific persisted query, so restored filters are visible from the first dashboard paint
- Added per-chart horizontal CDF range sliders with an automatic multi-series default cutoff based on the highest X value shared by at least two curves
- Simplified the default CDF slider cutoff back to the last X value still shared by at least two curves; `Single CDF` keeps the full range by default
- Refined the default CDF slider cutoff to use the lower of the shared multi-curve X limit and the point where all visible curves have already reached 0.95 on the Y axis
- Fixed bar-chart normalization so the highest bar always reaches the top of the Y axis even when every value is below `1`
- Added CDF axis labels and metric units in dashboard and export charts so the plotted values are identifiable at a glance
- Updated PowerPoint chart exports to honor each CDF chart's default horizontal X range and to render vertical Y-axis labels for both CDF and bar charts
- Added CDF axis ticks/grid lines to PowerPoint exports and moved PowerPoint vertical axis labels closer to the plotted Y axes for both CDF and bar charts
- Strengthened PowerPoint CDF grid/tick rendering and moved PowerPoint vertical axis labels even closer to the Y axes so the changes remain visible after slide scaling
- Fixed PowerPoint metric KPI strips so all six KPI cards render instead of only `Max`
- Fixed data filter ordering so `Test Name` appears between `Vendor` and `Region`

#### 📚 Documentation:
- Added `Readme` and `Changelog` navigation with Markdown document viewer
- Added the app logo at the top of the `README`
- Fixed document links to open `Readme` and `Changelog` in a new tab
