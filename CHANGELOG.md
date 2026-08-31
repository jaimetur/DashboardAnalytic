# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.0
### Release Date: 2026-08-31
#### 🌟 New Features:
- Reorganised the application into **Workspace**, **E2E Dashboard** and **E2E PowerPoint Reporting** modules, with a Smart Orchestrator Logs Reports entry point.
- Added CDR ingestion classification and optional Vendor mapping for Data, Voice and Speech, including VFUK/3UK mappings, batch review, queued mapping and queued clearing.
- Added template-driven NetCheck PowerPoint reporting, including multi-campaign Data/Voice/Speech reports, run traceability and timestamped outputs.
- Added Slides Templates Management for NSA/SA: import and legacy conversion, defaults, type reassignment, duplicate/delete/export and in-browser editing.
- Added multi-workspace support. Workspaces can be created, opened, closed, renamed, duplicated and removed; each keeps its database and files under `data/workspaces/<Workspace Name>/`. Log in opens the selected workspace, preselecting the most recently used one.
- Added Database Management in Admin to browse, edit, filter and delete rows from tables in the active workspace database.
- Added processed-dataset previews, direct CDR **Show Dashboard** access, and Dashboard **Preview Dataset** access.
- Added Admin **Import/Export** ZIP packages for configuration, shared Slides Templates, individual workspaces and full-environment transfers. Imports detect the package type automatically and register imported workspaces locally.

#### 🚀 Enhancements:
- Added editable root-level `storage-paths.conf` for configuring `CONFIG_DIR`, `DATA_DIR` and `ASSETS_DIR` without editing Python; deployment environment variables retain precedence.
- Kept project-local `config/`, `data/` and `assets/` as the automatic fallback when `storage-paths.conf` is absent.
- Made Slides Templates executable: catalogue source, KPI, chart type, filters, thresholds/buckets, legend, grouping and named layout drive rendering, including structural Title and Transition slides.
- Unified NSA, SA, single-vendor and multivendor generation on the master `Template_CDR_analysis.pptx`; catalogues create slides and populate layout placeholders. NSA/SA catalogues were also aligned with the NetCheck methodology.
- Improved multivendor reporting with persisted VFUK/3UK GCID and Vendor calculations, UK operator-name normalisation at render time, and validation that all selected CDRs are mapped.
- Accelerated repeated multi-campaign reports with shared SQLite CDR tables synchronised by `dataset_id`; reports query only the fields required by the selected template.
- Added Admin Datasets Management with safe dataset-file renaming, source-path synchronisation and operational actions.
- Improved previews and the database editor with materialised GCID, source-preserving fields, searchable Excel-style multi-value filters, contextual values across all pages and configurable row limits.
- Expanded the Slides Templates Editor with contextual help, Filter Builder, searchable selections, fixed columns, row controls and scroll guidance.
- Simplified template persistence: SQLite stores only each CSV's exact name, type and default state. Names preserve case and spaces, and renames/duplicates keep files and defaults in sync without JSON registries or slug aliases.
- Improved CDR-only Dashboard analysis, adaptive filters, responsive module UI, dialogs, admin actions and Help navigation.
- Moved Slides Templates to the shared `config/slides-templates/` library and removed unused workspace `output/` directories.
- Made configuration transfers preserve the destination workspace registry; full-environment imports rebuild it from the transferred workspaces to avoid source-path conflicts.
- Moved the workspace registry to `data/workspaces/workspace-registry.db`, with automatic migration from both historical `config` filenames.
- Added package preflight warnings and explicit confirmation before Import/Export overwrites configuration, shared templates or a same-named workspace.
- Removed combined-CDR cleanup from Admin page load; it now runs after dataset deletion or from Database Management's **Clean orphaned rows** action.
- Improved generated PowerPoint charts with larger legends, labels and axis ticks; hierarchical grouping now keeps child dimensions nested below their parent, and CDF campaign lines increase in width from oldest to newest.
- Keep multi-level chart categories together even when CDRs are appended campaign by campaign: all child bars now appear beneath one parent label (for example, every Vodafone campaign before O2).
- Added a `Legend Position` Slides Template column. Charts now place legends at Top, Bottom, Left or Right, using rows for top/bottom and columns for left/right; the existing shared-library templates are explicitly populated as Right for one-column layouts and Bottom for multi-chart layouts.
- Made Admin ZIP exports disk-backed background jobs with direct, resumable browser downloads, selective compression for already-compressed files and 24-hour cleanup of temporary packages; this supports very large workspaces without loading the archive into browser or server memory.
- Show an immediate upload-progress dialog when importing a ZIP, before a large package reaches the server for overwrite inspection.

#### 🐛 Bug fixes:
- Removed the unused `assets/slides-templates` migration path; Slides Templates now use only the configured shared library.
- Fixed external `CONFIG_DIR`, `DATA_DIR` and `ASSETS_DIR` deployments so startup recognises an already-migrated workspace database instead of attempting to overwrite it with the legacy configuration database.
- Fixed catalogue defaults, deletion protection, editor selection, grouping semantics and reporting placeholder/chart generation.
- Fixed CDR and mapping ingestion for duplicate headers, legacy encodings, alternate Cell ID fields, VFUK/3UK GCIDs and NSA RAT spellings.
- Fixed Vendor persistence and preview ordering, and kept CDRs usable after failed mapping while logging the failure.
- Fixed inline template renames so selectors, URLs and the open editor refresh immediately; aligned template-management controls and feedback dialogs.
- Fixed Workspace drag-and-drop, cache/profile refreshes, queue action updates and Dashboard filter population/contrast.
- Fixed queued imports so they retain their originating workspace and continue after closing it or signing out.
- Preserved original upload dates during reprocessing, separating **Uploaded** from **Updated** and keeping automatic latest-dataset selection stable.
- Recovered legacy CDRs left failed by Vendor mapping by rebuilding their original source without a mapping.
- Fixed Help navigation and mobile document overflow.

#### 📚 Documentation:
- Replaced inherited documentation and the root-level roadmap with numbered Dashboard Analytic Help and an embedded index.
- Expanded README and Help for ingestion, mapping, previews, Dashboard, reporting and Slides Templates.
- Documented shared template storage, workspace data layout and Admin Import/Export transfer behaviour.

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
