# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.1
### Release Date: 2026-09-03
#### 🌟 New Features:

#### 🚀 Enhancements:
- Moved Report Charts rendering to an independent persistent background queue with progress, retry and a separate Charts Jobs panel below Reports Jobs.
- Improved Reports Jobs and Charts Jobs with type, template, scope, dataset and chart metadata, clearer panel names, bulk deletion controls and consistent job-count sizing.
- Made Open from Charts Jobs load and select the corresponding Charts Set, expand Report Charts and scroll directly to it.
- Automatically opens Report Charts and scrolls to the completed Chart Set when a newly queued or retried Charts Job becomes ready.
- Stored each generated PowerPoint report with its rendered PNG charts in a dedicated `output/reports/<report-name>/report-charts/` folder, and moved independent Chart Sets to `output/charts/`.
- Renamed the Report Charts panel to Charts Panel and unified its selector: it now lists standalone Chart Sets and report-rendered chart sets with clear source prefixes.
- Added Delete All Reports to Charts Panel next to its Chart Set cleanup controls.
- Added ZIP downloads for standalone Chart Set PNGs and for the PNG charts rendered with each generated report; Charts Jobs now uses the same eye action as Reports Jobs.
- Improved Charts Set selection with report-first chronological ordering, clear source-specific hover styling and automatic closing when clicking elsewhere.
- Renamed newly generated report files to use the clearer `_by-operator_` and `_by-vendor_` scope tokens.
- Added a Multivendor multi-campaign review dialog before report or Chart Set generation, with one-or-more CDR validation for Data, Voice and Speech and the chronologically latest selected campaign preselected for each type.
- Made Count Stacked Horizontal Bars retain every filtered Rows/Columns Aggregation value, drawing zero-count combinations instead of omitting them.
- Added dashed vertical separators between child column-aggregation values, such as campaigns, within the same top-level group in Count Stacked Horizontal Bars.
- Made Slides Templates Editor saves asynchronous with immediate progress and confirmation dialogs, preserving the open editor, table state and scroll position.
- Added Escape-key dismissal for the floating Slides Templates Editor Cell Assistance panel.
- Added a brief grace period before the Charts Set selector closes after the pointer leaves it.
- Enlarged contextual Cell Assistance for Filters and Legend Position so filter values and every legend-placement option remain readable.
- Restored existing filter clauses into the Cell Assistance Filter Builder and refined its compact light selector styling.
- Added comma-separated multi-value support for Filter Builder `CONTAINS` and `NOT CONTAINS` conditions.
- Improved hierarchical column charts with a single caption orientation, vertical KPI y-axis labels, and stable operator/vendor colours (Vodafone red, 3 orange, O2 blue and EE turquoise) whenever an operator/vendor is a column-aggregation dimension, including distinct shades for multivendor groups.
- Refined CDF rendering with thin baseline lines, emphasis only for the latest campaign in multi-campaign comparisons, and non-overlapping legend markers and labels.
- Made CDF Line generate one curve for every complete Rows/Columns Aggregation combination, regardless of which axis defines each dimension.
- Made dense CDF legends compact and canvas-aware, and enlarged the chart viewer to keep every legend row visible.
- Added consistent dashed separators to hierarchical vertical-bar charts, only at changes in the top-level column aggregation, and strengthened CDF campaign detection from the physical Campaign field for reliable historical/latest line widths and operator/vendor palette assignment.
- Completed hierarchical failure-count comparison grids so empty Operator/Vendor × Campaign combinations remain visible, with dashed separators only between distinct top-level column-aggregation values.
- Expanded multivendor chart palettes so each vendor receives a distinct shade within its operator family, while campaigns for that vendor retain the same hue.
- Made single-campaign CDF Lines use the same emphasised stroke width as the latest campaign in a multi-campaign comparison.
- Standardised vendor colour families across every chart type: Ericsson green, Huawei red, Samsung yellow and NSN blue, with distinct shades when the same vendor appears for multiple operators.
- Added an overwrite confirmation when importing a Slides Template whose name already exists; overwriting the default also refreshes its active CSV.
- Made Template to edit open the chosen Slides Template immediately, prompting to save or discard any pending edits before switching tables.
- Trimmed CDF Line x-axes only after at least three curves strictly exceed 98% and converge with one another, avoiding premature loss of meaningful CDF data.
- Made Slides Template saves atomic and short-lived: CSV replacement completes before metadata/audit work is deferred, reducing failures during server load.
- Stopped template edits from regenerating the PowerPoint help document, removing an unnecessary synchronous filesystem write from every save.

#### 🐛 Bug fixes:
- Unified completed Chart Set timestamps across the Charts Jobs date, `Generated at` badge, selector label and timestamped output folder.
- Fixed the Reporting CDR multi-select menus retaining stale checkmarks after confirming the Multivendor campaign review; their displayed choices now match the submitted CDRs.
- Fixed Report Charts failures to return actionable JSON errors and record Error events in App Logs instead of exposing a browser JSON parsing error.
- Fixed deleted Chart Sets leaving stale completed jobs in Charts Jobs, including single-set and all-set deletion.
- Fixed Delete All Reports routing and its error dialog so validation failures no longer result in an empty `[object Object]` message.
- Fixed build_docker.yml workflow to always update tag:latest.
- Fixed Slides Template CSV exports adding technical technology/template suffixes; downloads now use the template's exact visible name.
- Fixed Slides Templates Editor selection and registry stability: browser-restored picker values can no longer claim a different open template, and unregistered library CSVs no longer appear as phantom templates.

#### 📚 Documentation:
- Rewrote the PowerPoint Reporting help as static guidance for building Slides Templates, including field-by-field instructions and practical recipes for every chart type, filters, aggregations, legends, structural slides, operators and output jobs.

---

## Release: v0.2.0
### Release Date: 2026-08-31
#### 🌟 New Features:
- Added modular Workspace, Dashboard and PowerPoint Reporting areas, including the Smart Orchestrator Logs reporting entry point.
- Redesigned the web UI with dedicated Workspace, Dashboard, Reporting and Admin panels.
- Added Data, Voice and Speech CDR ingestion with VFUK/3UK vendor mapping and review queues.
- Added template-driven NSA/SA and multivendor PowerPoint reporting.
- Added multi-campaign CDR comparison reports across Data, Voice and Speech.
- Added shared Slides Templates Management and Editor with import, export, defaults, duplication and deletion.
- Added independent workspace lifecycle management: create, open, close, rename, duplicate and remove.
- Added Database Management for browsing, editing and deleting records, with paginated Excel-style column filters.
- Added Import/Export ZIP packages for configuration, Slides Templates, individual workspaces and full environments.
- Restricted configuration and workspace Import/Export to `super-admin`; `admin` users can transfer only shared Slides Templates.
- Added global user, role and workspace-access administration, including the `super-admin` role.
- Added self-service password changes from the header User badge.
- Added processed-dataset preview and direct Preview/Show Dashboard actions in Workspace and Admin.
- Added persistent Generated Reports Jobs with progress, metadata, Download and Delete actions.
- Added blank Slides Template creation from the library, ready for direct renaming and editing.
- Added a dedicated App Logs tab that combines operational and audit activity, exposes up to 1,000 events and provides persistent user, date, type and action filters.
- Added Report Charts to render every automated chart in the selected report template without creating a PowerPoint file.

#### 🚀 Enhancements:
- Added root-level `storage-paths.conf` with `APP_CONFIG_DIR`, `APP_DATA_DIR` and `APP_ASSETS_DIR` overrides.
- Consolidated global users and Slides Template registry data in `config/application.db`.
- Moved templates, workspace databases, reports and registry files to dedicated configuration/data locations.
- Expanded template definitions with chart titles, filters, row/column aggregations, legends and `Legend Position`.
- Ordered and visually grouped multi-chart slides in the Editor while preserving complete CSV data on save.
- Optimised repeated CDR reports with shared materialised tables and report-specific column loading.
- Improved Dashboard and preview performance, adaptive filters, vendor persistence and large-dataset handling.
- Added safe dataset renaming with synchronised source paths and references.
- Added orphaned combined-CDR row cleanup after dataset deletion and from Database Management.
- Added Excel-like preview filtering and global CDR pre-filters for Operator, Vendor, RAT, Session Type, Call Status, Call Family and Test Family.
- Added colour cues for Source Sheet, Vendor and GCID fields in dataset previews.
- Added Slides Templates Editor cell assistance, contextual help, searchable selectors and row insertion.
- Added reusable blank PowerPoint layouts and CSV-defined slide/chart templates.
- Improved PowerPoint readability, hierarchical grouping, campaign-weighted CDFs and configurable legend placement.
- Made imports, exports, large ZIP transfers and report generation disk-backed background jobs with progress, overwrite warnings and session-independent execution.
- Expanded Generated Reports Jobs with report metadata, local server dates, alternating rows and compact Download/Delete actions.
- Improved user administration with searchable workspace-access pickers, automatic validated saves, password masking/reset controls and role-labelled default access.
- Improved Database Management labels by separating Config Tables from Workspace Tables.
- Renamed template audit-log terminology from `catalogue` to `template`.
- Mark interrupted dataset-processing and report-generation jobs as retryable failures after an application restart, with Report Job retry actions.
- Added Created and Last Updated timestamps plus direct Edit actions to the Slides Templates Library, and standardised its HTTP routes on `report-templates`.
- Kept the current module open when switching the active workspace from the header.
- Serialised dataset processing per workspace so retries wait as queued work while another dataset is processing.
- Materialised `Call Family` and `Test Family` as inspectable CDR dimensions, with light-grey Preview styling for derived fields.
- Added per-chart Slides Templates Editor previews using the current unsaved filters, aggregations and resolved derived dimensions.
- Added per-chart generated-image previews in the Slides Templates Editor, using the same renderer as PowerPoint report generation.
- Added a dedicated Application Logs tab to view Application Activity with all the events.
- Made Reporting panels collapsible and added a module selector that switches between NetCheck CDR Reports and Smart Orchestrator Logs Reports.
- Added Generate Report Charts to E2E Reporting module to visualize all Charts included in the pre-selected report.
- Persisted Report Charts as selectable timestamped workspace sets, with template labels, complete-set deletion and an enlarged first/previous/next/last viewer.
- Expanded Report Charts set controls with scope-aware selection plus selected-set and confirmed all-set deletion.
- Added per-source CDR counts to persisted Report Charts sets, their selector labels and report metadata badges.
- Unified PowerPoint and Report Charts rendering, clarified missing hierarchy combinations, and rotated crowded chart grouping labels by 45°.
- Reserved adaptive chart title and row-label gutters so hierarchical captions no longer overlap plots or axes.
- Improved dense horizontal failure charts with centred count labels and visible fallbacks for narrow stacked segments.

#### 🐛 Bug fixes:
- Preserved all chart-definition values during template migration, normalisation, sorting and visual merging; fixed defaults, renames, deletion protection, editor selection and report placeholder generation.
- Fixed CDR ingestion and mapping for duplicate headers, alternate encodings, Cell ID variants and vendor fields; failed mappings no longer hide datasets and failed imports can recover.
- Fixed dataset queue ownership, upload/update dates and background processing when a workspace closes or a user logs out.
- Fixed Dashboard filter restoration, cache invalidation, empty states and mobile document overflow.
- Fixed report generation for missing sources, empty tables, duplicate columns, mixed encodings and legacy metadata; child campaign bars now remain nested under their operator.
- Fixed report-job file discovery and historical-job loading after the move to `output/reports/`, and prevented obsolete workspace `exports/` directories from being recreated.
- Fixed Docker packaging of the master PowerPoint template and local-time handling through `TZ` (default `Europe/Madrid`).
- Fixed host-specific storage paths from breaking CI or other deployments, and standardised local-time persistence/display for queues, profiles, logs, users, workspaces and report jobs.
- Fixed Admin loading with no active workspace or default template.
- Removed obsolete `config/app.db` and legacy workspace copies of global tables; `config/application.db` is the sole global configuration database.
- Prevented stale SQLite sidecars and obsolete user records from overriding configuration imports; users, roles, IDs and workspace access now restore exactly.
- Fixed case-insensitive usernames across login, password changes and workspace access, including case-only duplicate prevention and a clear warning for unauthorised workspace login.
- Enforced workspace-access and super-admin safeguards: only super-admins have implicit workspace access, protected roles cannot be altered by lower roles, and the last active super-admin cannot be removed, demoted or deactivated.
- Fixed workspace-access picker visibility, clipping, alignment and save synchronisation between Workspace Management and Users.
- Fixed the Users table showing browser-restored form values instead of current database records after configuration imports or navigation restores.
- Fixed blank Slides Templates so they open as an editable empty canvas, and fixed the editor selector to always show the template actually opened.
- Fixed queued dataset and report jobs left by an application restart so they become retryable failures instead of remaining stalled.
- Fixed large workspaces delaying application startup while derived CDR fields were being backfilled; older datasets now update on first Preview or Reporting use.
- Fixed report materialisation of equivalent CDR headings (for example `G_Level_4` / `G Level 4`) and refreshed stale derived dimensions so PPT and Report Charts receive the same source fields as the editor.
- Reserved a dedicated right-side legend lane in hierarchical failure charts so legends no longer overlap rotated column headings.
- Fixed Generated Reports Jobs width stability while reports are processing, preventing the longer status badge from pushing the table outside its panel.

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
