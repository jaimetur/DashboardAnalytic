# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.0
### Release Date: 2026-08-30
#### 🌟 New Features:
- Split the product into the top-level **Workspace**, **E2E Dashboard** and **E2E PowerPoint Reporting** modules, with a future-ready **Smart Orchestrator Logs Reports** entry point.
- Added per-file Workspace classification for NetCheck CDR Data, Voice and Speech, Smart Orchestrator Logs, VFUK and 3UK mappings, with filename detection and batch review.
- Added optional CDR Vendor mapping during import: each CDR can select the latest ready VFUK and/or 3UK mapping, or retain **No Map Vendor Column**.
- Added queued batch Vendor mapping from Workspace: select multiple unmapped CDRs, use the latest VFUK/3UK mappings by default, and follow each non-blocking task through the existing queue progress bar.
- Added queued batch Vendor clearing: select one or more mapped CDRs and restore their source processing in the same non-blocking Workspace queue.
- Added NetCheck CDR PowerPoint reporting from processed Data, Voice and Speech inputs, with report-run traceability and timestamped filenames.
- Added multi-campaign reporting: select multiple CDRs for Data, Voice and/or Speech and the tool concatenates each source with its union of columns, preserving Campaign values for benchmark comparisons.
- Added embedded Help with consistently numbered navigation and recommended reading (`00` to `09`), including the explicit **04. E2E Dashboard** and **05. E2E PowerPoint Reporting** sections.
- Added processed-dataset previews, direct CDR-only **Show Dashboard** access and matching Dashboard **Preview Dataset** access.
- Added workspace Slides Templates Management: named NSA/SA imports, conversion of compatible legacy CSVs, defaults, duplication, deletion, export and in-browser editing.

#### 🚀 Enhancements:
- Unified NSA, SA, single-vendor and multivendor rendering on the master/layout-only `Template_CDR_analysis.pptx`; the selected catalogue creates slides and fills layout placeholders in row-major order.
- Made Slides Templates executable: source, KPI, generic chart type, filters, thresholds/buckets, legend, `Grouping_Rows`, `Grouping_Columns` and named layout now drive rendering. Structural **Title Slide** and **Transition Slide** rows are also supported.
- Reworked NSA/SA catalogues against the NetCheck methodology, split multi-chart screenshots into separate rows/layouts, and completed the requested NSA KPI, source, filter and grouping definitions through slide 21.
- Improved multivendor processing: VFUK/3UK GCID lookups and the agreed first/last-cell Vendor formula are persisted on CDRs
- Reporting enables Multivendor only when all selected CDRs are mapped and transforms Operator displays to Vendor without changing stored filters or catalogues.
- Expanded mapping and CDR previews with materialised GCID, source-preserving fields, column/row search, Excel-style multi-value filters, CDR-specific filters and configurable row limits. Workspace now uses persisted profiles for faster loading.
- Restricted Dashboard analysis to CDR datasets and meaningful KPI fields; improved adaptive-filter normalisation, responsive layouts, previews and exports.
- Refined the responsive tabbed UI, module palettes, action controls, loading dialogs and Help navigation across Workspace, Dashboard, Reporting and Admin.
- Added a reporting catalogue selector that follows the NSA/SA workspace default while allowing a per-report override.
- Expanded the in-browser Slides Templates Editor with contextual assistance, Filter Builder, searchable single/multi-select values, fixed action/Slide columns, row movement/insertion/removal, re-enumeration and scroll guidance.
- Refactored PowerPoint and Slides Templates storage: the master deck lives in `assets/ppt-templates/`; `assets/slides-templates/library/` is the complete canonical NSA/SA template library (including defaults), `default/nsa/` and `default/sa/` hold only the active generation mirrors, and the root registry keeps names, defaults and file renames synchronized.
- Unified Slides Template naming so the visible template name is also the exact physical CSV filename, preserving case and spaces across library, default mirror, imports, renames and duplicates.
- Standardized Administration and Help labels on **Template** terminology.
- Renaming a named workspace catalogue now also renames its managed CSV file and preserves its default selection.
- Added timestamped report filenames, `UpdateAll.py`, and removed obsolete release-document tooling.

#### 🐛 Bug fixes:
- Consolidated catalogue import, conversion and status feedback into single-action floating dialogs; Admin actions and inline renames retain the current scroll position.
- Corrected default-catalogue state, deletion protection, editor selection and Reporting defaults for datasets and catalogues.
- Corrected catalogue grouping semantics across bars, CDF, scatter and tables; nested row/column hierarchies, distribution stacks and campaign labels now render consistently.
- Fixed master-layout placeholder assignment, inherited-chart cleanup, generated-report download completion and Help article navigation.
- Fixed CDR/mapping ingestion for duplicate headers, legacy CSV encodings, VFUK/3UK GCIDs, alternate Cell ID fields (including Global CI/GCID/GCI/CGI/ECI variants) and NSA RAT spellings.
- Fixed Workspace drag-and-drop, cache refreshes, profile-backed loading and Dashboard filter population/contrast.
- Fixed live Workspace queue updates so newly processed CDRs immediately show the applicable **Map Vendors**, **Clear Vendors** and **Show Dashboard** actions: the Workspace now refreshes itself once when background processing reaches Ready, using the final server profile.
- Fixed mobile README/document overflow by constraining rendered images and the Markdown container, including the application logo.

#### 📚 Documentation:
- Replaced inherited documentation and the root-level roadmap with a maintained numbered Dashboard Analytic Help set and embedded index.
- Expanded README and Help for ingestion, CDR/multivendor mapping, previews, Dashboard, reporting, catalogue conversion/editor and grouping behaviour.

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
