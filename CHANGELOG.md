# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.0
### Release Date: 2026-08-27
#### 🌟 New Features:
- Split the product into the top-level **Workspace**, **E2E Dashboard** and **E2E PowerPoint Reporting** modules, with a future-ready **Smart Orchestrator Logs Reports** entry point.
- Added per-file Workspace classification for NetCheck CDR Data, Voice and Speech, Smart Orchestrator Logs, VFUK Vodafone and 3UK Three Multivendor Mappings, including filename-based preselection and batch review.
- Added NetCheck CDR PowerPoint reporting from processed Data, Voice and Speech inputs, using the bundled NSA/SA templates and mandatory VFUK Vodafone/3UK Three mappings for multivendor runs, with persistent report-run traceability.
- Added embedded Help with consistently numbered navigation and recommended reading (`00` to `09`), including the explicit **04. E2E Dashboard** and **05. E2E PowerPoint Reporting** sections.
- Added a read-only processed-dataset preview from the Workspace queue, with a direct CDR-only **Show Dashboard** action.

#### 🚀 Enhancements:
- Reworked template-backed CDR rendering into an explicit NSA/SA slide contract: each automated slide now selects its CDR source, technology/session/test/direction filters, KPI and template chart grammar (100% stacked columns, stacked failure counts, CDF lines, mean/median bars or scatter) rather than reusing one generic bar chart. The complete catalog now records CDR source, KPI, chart type, filters and grouping per chart (one row per chart), with matching editable NSA/SA CSV exports.
- Rebased the NSA catalogue on the NetCheck CDR Dictionary and benchmarking methodology: it now uses the documented call families, data-test fields, FDFS transfer duration, interactivity packet-error KPI and the DL/UL FDTT bucket definitions from the template.
- Added an explicit `Layout` catalogue field. The renderer validates the named master layout, clears the inherited sample-chart placeholders, populates only its chart areas, leaves analyst comments blank and renders CDF lines separately from mean/median bar charts.
- Split NSA template screenshots that contained several charts into independent catalogue rows and matching row/column layouts, including the two data-success charts on slide 10 and the three WhatsApp POLQA visuals on slide 13.
- Assigned the NSA WhatsApp POLQA slide's three independent charts to the equal-width three-column layout.
- Standardized preserved template entries as `Not Automated (preserve)` and recorded the NSA conclusions slide as its existing preserved `Table`.
- Added Admin export/import for NSA and SA Slide Catalogue CSVs stored in `assets/ppt-slides-catalog/`; active catalogues drive report generation, refresh the related Help tables and retain slide titles, subtitles and matching master layouts.
- Standardized validated, dataset-agnostic chart types around explicit geometry and aggregation: vertical/horizontal bars, CDF, scatter and tables.
- Made catalogue filters, threshold/bucket settings and `×` grouping hierarchies executable, driving CDR selection, aggregation, axes, series, stacks and table layout.
- Restricted E2E Dashboard dataset selection and exports to NetCheck CDR Data, Voice and Speech sources; VFUK/3UK mappings and Other inputs remain separately classified in Workspace but are no longer dashboard candidates.
- Excluded geographic coordinates, cell/network identifiers and other technical metadata from the Dashboard metric selector.
- Refined the tabbed interface: product and documentation/admin tabs align with the primary panel, have distinct active colours and matching gradients, and respect Admin visibility.
- Unified the Workspace, Dashboard, Reporting and Admin visual palettes, including action buttons, labels, toggles, readable Adaptive Filters and dark Dashboard KPI subcards.
- Improved Reporting selector contrast with light-purple selected and focus states instead of the unreadable intense-blue browser treatment.
- Completed the reporting workflow with RAT-based NSA/SA filtering, CDR Cell ID endpoints, 3UK `Cid__ECI` and VFUK 4G GCID lookups, the agreed vendor formula, multivendor-only VFUK/3UK selectors populated only from matching processed Workspace mappings, persisted-row charts, blank analyst commentary areas and `APP_REPORTING_TEMPLATE_DIR` overrides.
- Improved Workspace data access with an alphabetical **All Types** queue filter, disabled unavailable types, ordered **Preview**/**Show Dashboard** actions, two-axis preview scrolling, all dataset columns and configurable preview rows (100 by default). Opening or refreshing a preview displays the generation dialog. VFUK and 3UK mappings materialize a yellow highlighted first-column `GCID` (from the VFUK calculation or 3UK ECI respectively) and highlight their Vendor field in soft blue; mapping previews support Vendor and exact-GCID filters, show source fields rather than empty normalization or unnamed duplicate fields, format GCID as an integer identifier, and VFUK shows exactly the columns of the selected `4G`/`5G` source sheet without exposing its technical `source_sheet` column. Preview column counters now match the rendered table. Older mappings are upgraded automatically when opened.
- Added **Preview Dataset** to the E2E Dashboard Selected Dataset panel, reusing the same processed-data preview, row-limit controls, filters and loading dialog as Workspace.
- Kept Dashboard **Preview Dataset** left-aligned while Word and PowerPoint exports remain right-aligned in their shared action row; made Dashboard panels, controls and KPI cards fluid at mobile widths.
- Refined operational navigation with the username beside Logout, `00. Help Home 🏠` first and Help articles numbered directly from their filenames (`00` to `09`).
- Expanded module descriptions, README and Help guides to document the current operational workflow; standardized the **Generate PowerPoint Report** and **Refresh Preview** controls.
- Named generated NetCheck CDR PowerPoint reports with their generation timestamp (`yyyymmdd-hhmm`) instead of an opaque content-hash suffix.
- Created `UpdateAll.py` as a Dashboard Analytic utility for synchronizing `src/version.py` and the current `CHANGELOG.md` release header.

#### 🐛 Bug fixes:
- Switched VFUK GCID resolution to the supplied 4G `eNodeB ID`/`Local Cell ID` hexadecimal-equivalent formula and accepted the Cell ID field variants used by Data, Voice and Speech CDRs.
- Made Excel worksheet headers unique during ingestion, preventing VFUK mappings and CDR workbooks with duplicate or blank headers from failing during Pandas reindexing.
- Added Windows-1252 and Latin-1 CSV decoding fallbacks after UTF-8, allowing 3UK Multivendor Mapping files with legacy characters to process correctly.
- Removed the obsolete `DOWNLOAD.md` dependency from `BuildBinary.py`; binary release notes now come directly from `CHANGELOG.md`.
- Removed the obsolete PhotoMigrator-only `UpdateDownloadLinks.py` utility, which referenced unavailable documentation and release links.
- Improved contrast for Workspace status and Dashboard summary cards, user identity and Logout controls.
- Fixed Data Ingestion drag-and-drop and cache versioning so new static styles are reliably applied.
- Accepted the NetCheck `EN-DC`, `EN DC` and `ENDC` NSA RAT spellings.
- Replaced inherited example charts in generated CDR presentations and regenerated reports when the renderer changes.
- Closed the report-generation dialog after a successful download and fixed Help sidebar navigation to open individual articles.

#### 📚 Documentation:
- Replaced inherited and unrelated documentation, including the root-level roadmap, with a maintained numbered Dashboard Analytic Help set and embedded Help index.
- Documented the E2E module structure, ingestion classification, multivendor prerequisites, reporting workflow and template configuration in the README and Help guides.

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
