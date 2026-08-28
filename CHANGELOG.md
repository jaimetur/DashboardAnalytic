# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.0
### Release Date: 2026-08-30
#### 🌟 New Features:
- Split the product into the top-level **Workspace**, **E2E Dashboard** and **E2E PowerPoint Reporting** modules, with a future-ready **Smart Orchestrator Logs Reports** entry point.
- Added per-file Workspace classification for NetCheck CDR Data, Voice and Speech, Smart Orchestrator Logs, VFUK Vodafone and 3UK Three Multivendor Mappings, including filename-based preselection and batch review.
- Added NetCheck CDR PowerPoint reporting from processed Data, Voice and Speech inputs, using the bundled NSA/SA templates and mandatory VFUK Vodafone/3UK Three mappings for multivendor runs, with persistent report-run traceability.
- Added embedded Help with consistently numbered navigation and recommended reading (`00` to `09`), including the explicit **04. E2E Dashboard** and **05. E2E PowerPoint Reporting** sections.
- Added a read-only processed-dataset preview from the Workspace queue, with a direct CDR-only **Show Dashboard** action.

#### 🚀 Enhancements:
- Unified NSA, SA, single-vendor and multivendor generation on the single master/layout-only `Template_CDR_analysis.pptx`, with no source slides. The selected catalogue supplies the technology-specific structure and the renderer creates exactly one slide per catalogue number, applying its named layout and filling chart placeholders in row-major order.
- Added catalogue-native `Title Slide` and `Transition Slide` types for covers and section dividers. They populate title/subtitle placeholders without accepting CDR, KPI, chart, legend, filter or grouping fields; legacy preserve rows are converted to the corresponding structural format.
- Reworked template-backed CDR rendering into an explicit NSA/SA slide contract: each automated slide now selects its CDR source, technology/session/test/direction filters, KPI and template chart grammar (100% stacked columns, stacked failure counts, CDF lines, mean/median bars or scatter) rather than reusing one generic bar chart. The complete catalog now records CDR source, KPI, chart type, filters and grouping per chart (one row per chart), with matching editable NSA/SA CSV exports.
- Rebased the NSA catalogue on the NetCheck CDR Dictionary and benchmarking methodology: it now uses the documented call families, data-test fields, FDFS transfer duration, interactivity packet-error KPI and the DL/UL FDTT bucket definitions from the template.
- Split NSA template screenshots that contained several charts into independent catalogue rows and matching row/column layouts, including the two data-success charts on slide 10 and the three WhatsApp POLQA visuals on slide 13.
- Assigned the NSA WhatsApp POLQA slide's three independent charts to the equal-width three-column layout.
- Standardized preserved template entries as `Not Automated (preserve)` and recorded the NSA conclusions slide as its existing preserved `Table`.
- Added Admin export/import for NSA and SA Slide Catalogue CSVs stored in `assets/ppt-slides-catalog/`; active catalogues drive report generation, refresh the related Help tables and retain slide titles, subtitles and matching master layouts.
- Standardized validated, dataset-agnostic chart types around explicit geometry and aggregation: vertical/horizontal bars, CDF, scatter and tables.
- Made catalogue filters, threshold/bucket settings and `×` grouping hierarchies executable, driving CDR selection, aggregation, axes, series, stacks and table layout.
- Restricted E2E Dashboard dataset selection and exports to NetCheck CDR Data, Voice and Speech sources; VFUK/3UK mappings and Other inputs remain separately classified in Workspace but are no longer dashboard candidates.
- Excluded geographic coordinates, cell/network identifiers and other technical metadata from the Dashboard metric selector.
- Refined the tabbed interface: product and documentation/admin tabs align with the primary panel, have distinct active colours and matching gradients, and respect Admin visibility. On mobile, documentation/admin tabs occupy the upper row while the main modules use compact **Workspace**, **Dashboard** and **Reporting** labels below.
- Unified the Workspace, Dashboard, Reporting and Admin visual palettes, including action buttons, labels, toggles, readable Adaptive Filters and dark Dashboard KPI subcards.
- Improved Reporting selector contrast with light-purple selected and focus states instead of the unreadable intense-blue browser treatment.
- Completed the reporting workflow with RAT-based NSA/SA filtering, CDR Cell ID endpoints, 3UK `Cid__ECI` and VFUK 4G GCID lookups, the agreed vendor formula, multivendor-only VFUK/3UK selectors populated only from matching processed Workspace mappings, persisted-row charts, blank analyst commentary areas and `APP_REPORTING_TEMPLATE_DIR` overrides.
- Improved Workspace data access with an alphabetical **All Types** queue filter, disabled unavailable types, ordered **Preview**/**Show Dashboard** actions, two-axis preview scrolling, all dataset columns and configurable preview rows (100 by default). Opening or refreshing a preview displays the generation dialog. VFUK and 3UK mappings materialize a yellow highlighted first-column `GCID` (from the VFUK calculation or 3UK ECI respectively) and highlight their Vendor field in soft blue; mapping previews support Vendor and exact-GCID filters, show source fields rather than empty normalization or unnamed duplicate fields, format GCID as an integer identifier, and VFUK shows exactly the columns of the selected `4G`/`5G` source sheet without exposing its technical `source_sheet` column. Preview column counters now match the rendered table. Older mappings are upgraded automatically when opened.
- Added optional per-CDR Vendor mapping during Workspace import, for both single-file and batch uploads. When ready VFUK and/or 3UK mappings exist, each CDR classification row proposes the newest matching mapping in independent selectors; **No Map Vendor Column** skips either mapping, so VFUK-only, 3UK-only and dual mappings are all supported during processing.
- Added conditional **Map Vendors** actions for unassigned CDRs in Workspace. The dialog lists only ready VFUK and 3UK mappings available in that Workspace and persistently assigns only Vodafone UK/3UK samples from their Operator plus the first/last `Cell_ID_A`, using the agreed Vodafone/Three formula; compact CDR actions share one row, with Map Vendors last, a dedicated mapping colour, a narrower Progress column, readable dialogs and a complete step-by-step Vodafone/3UK rule shown directly in the mapping-file selection dialog. Cancel explicitly closes the mapping dialog without submitting; submitting valid mapping choices closes it immediately and displays a dedicated progress dialog while the CDR refreshes. Tool-applied mappings can be removed with a distinct pink-gradient **Clear Vendors** action before remapping from updated files, with an equivalent cleaning-and-refreshing progress dialog.
- Simplified Multivendor Reporting to use the Vendor mapping already persisted on selected CDRs: VFUK/3UK mapping selectors were removed, and the Multivendor scope is available only when every selected Data, Voice and Speech CDR has been mapped in Workspace. Multivendor rendering now transforms Operator grouping dimensions to Vendor, Operator legends to Campaign, and Operator wording in slide/chart titles to Vendor while preserving source Operator filters and the stored catalogue unchanged.
- Split executable slide aggregation into **Grouping_Rows** and **Grouping_Columns**. Rows now define chart categories/table rows; columns define comparison series/table columns, with the final column level used as the stack for distribution charts. Admin exports use this schema, while legacy catalogues remain readable during migration.
- Updated NSA slides 8–15 with the requested operator scope, G Level 4 and horizontal/vertical grouping rules, corrected Speech/LQ sources for POLQA slides, the 1.6 thresholds, and the VoLTE/MultiRAB call scope. Speech technology classification now falls back to VoLTE/EPSFB or VoNR call mode when `Sample_RAT_A` is blank, POLQA filters require completed Vodafone UK/3/EE samples, and the campaign-specific WhatsApp chart dynamically selects the latest available campaign. Restored the template city subtitle on slides 8–21.
- Aligned NSA slides 16–21 with the former catalogue: `Mean_Data_Rate` for FDTT, completed-result scope, the named FDTT/FDFS test variants, the three-operator comparison set, and the specific Interactivity and httpBrowser filters. Distribution charts retain `Rate Bucket` as the renderer-required column grouping.
- Rendered PowerPoint slide subtitles in the title placeholder itself: they now use a second line below the title, a smaller 16 pt font and the reporting blue accent.
- Extended NSA and SA Slide Catalogue CSVs with **Chart Tittle** and **Legend**. Chart titles drive the generated chart heading; comma-separated legend labels replace generated series/state captions in display order. Existing catalogue schemas remain import-compatible.
- Expanded **Slide Catalogue Management** with a named workspace library for multiple NSA and SA catalogues. Imports receive a distinct name, become active immediately, and can later be activated or exported individually; the active catalogue remains the report-generation and Help reference.
- Added a **Slide Catalogue** selector to E2E PowerPoint Reporting. It lists the stored NSA/SA catalogues for the chosen technology and applies the selected catalogue to that report only, without changing the global active catalogue.
- Made the Reporting catalogue selector default to the workspace catalogue activated with **Use**, including when switching between NSA and SA.
- Added an in-application **Slide Catalogue Editor** with a compact catalogue selector at its top. Any NSA or SA catalogue can be edited or exported directly in a fixed-height grid with horizontal/vertical scrolling and a fixed **Slide** column that remains visible during horizontal navigation; Slide Catalogue Management provides compact one-row imports, including a floating confirmation to convert compatible legacy CSV schemas to the current format and automatic chart-count-based layouts when legacy rows omit one, and a workspace catalogue list with automatic rename-on-change plus per-technology **Set Default**, duplicate, delete and export actions.
- Added inline Slide Catalogue Editor row controls to insert a sibling chart row, move a row up or down, or delete it before saving. Row order now directly controls the generated placeholder order for charts sharing a slide.
- Expanded contextual cell assistance with a complete bordered grid, editable manual values and searchable CDR-aware choices: every single- and multi-select list filters live while typing (replacing the current value on focus), with neutral high-contrast result menus; Layout, CDR Source, KPI and Chart Type use single selection; Grouping and Legend use preselected checkbox multi-selects; and the contextual Filter Builder loads, adds or removes Field/Operator/Value conditions (including `NOT IN` and `NOT CONTAINS`) which the report parser executes.
- Enhanced CDR previews with soft-blue Vendor and soft-yellow source_sheet columns, multi-select Operator, Vendor, RAT/RAT_A, Session Type and Call Status filters preselected to all available values; filter menus now layer above Sample Data instead of being obscured by the next panel.
- Optimized Workspace loading by using persistent Vendor-mapping and Vendor-completeness flags instead of reopening or scanning every CDR on each page load; legacy mapped CDRs are marked once during database initialization.
- Improved E2E Dashboard filters with compact, high-contrast light-blue hover/selected/focus states, a clearer **None Selected** empty state, and completed NetCheck `*_A` field normalisation so Adaptive Filters populate from processed CDR values (including existing datasets); Workspace/Dashboard previews now open in a new tab.
- Added **Preview Dataset** to the E2E Dashboard Selected Dataset panel, reusing the same processed-data preview, row-limit controls, filters and loading dialog as Workspace.
- Kept Dashboard **Preview Dataset** left-aligned while Word and PowerPoint exports remain right-aligned in their shared action row; made Dashboard panels, controls and KPI cards fluid at mobile/tablet widths, with compact date inputs aligned to filter control sizing and the full-width Selected Dataset panel above the Executive Dashboard and Adaptive Filters grid.
- Refined operational navigation with the username beside Logout, `00. Help Home 🏠` first and Help articles numbered directly from their filenames (`00` to `09`).
- Expanded module descriptions, README and Help guides to document the current operational workflow; standardized the **Generate PowerPoint Report** and **Refresh Preview** controls.
- Named generated NetCheck CDR PowerPoint reports with their generation timestamp (`yyyymmdd-hhmm`) instead of an opaque content-hash suffix.
- Created `UpdateAll.py` as a Dashboard Analytic utility for synchronizing `src/version.py` and the current `CHANGELOG.md` release header.
- Added client-side filtering to every dataset preview table. Column names and row values support case-insensitive partial matches, with comma-separated terms combined as an OR search; additionally, every column header opens an Excel-style searchable checklist of its distinct values, supporting multi-selection and combined filters across multiple columns without reloading the preview.
- Added an explicit `Layout` catalogue field. The renderer validates and assigns the named master layout to the generated slide, synchronizes its title/comments placeholders, clears inherited sample charts and fills every chart area in strict row-major order (top-left to top-right, then each following row), tolerating minor PowerPoint coordinate differences—including both rows of **Title and 2 rows + Comments right**—while leaving analyst comments blank and rendering CDF lines separately from mean/median bar charts.

#### 🐛 Bug fixes:
- Show Slide Catalogue import validation failures in a floating dialog after redirecting back to Admin, rather than leaving the cause embedded in the management panel.
- Show successful Slide Catalogue import confirmations in the same floating dialog instead of embedding status text in Slide Catalogue Management.
- Use a dedicated informational import dialog with one **Close** action (rather than a confirmation dialog); closing it removes the import query state with `history.replaceState`, preserving the current Admin page and scroll position.
- Preserve and restore the Admin scroll position across server-backed catalogue imports and confirmed catalogue deletions, so the returned informational dialog opens at the same point in the catalogue list.
- Split the catalogue library status into a dedicated **Default** column with accessible green checked/grey unchecked indicators; **Type** now shows only NSA or SA. Default catalogues cannot be deleted in either the UI or server route.
- Start the Slide Catalogue Editor without a loaded catalogue and require an explicit choice; its selector now displays the same catalogue as the editable grid once **Edit** is used, retains its scroll position when opened, and visibly prompts **Choose a catalogue to edit**. A non-active bundled default catalogue can now be removed from the workspace library after another catalogue is set as default.
- Label the current catalogue consistently as **Default** rather than **Active** in the editor and reporting catalogue selectors.
- Preserve the Admin scroll position for all server-backed catalogue library actions, including **Set Default**, **Duplicate** and **Delete**.
- Preselect the most recently uploaded ready Data, Voice and Speech CDRs in Reporting, and automatically select the NSA/SA **Default** slide catalogue whenever the report technology changes.
- Save catalogue name edits asynchronously when the name field loses focus, preserving the current Admin scroll position; form data is captured before the field is disabled, and any rename failure uses the single-action informational dialog.
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
- Corrected chart grouping semantics across CDF, scatter, mean/median bars, stacked status/failure/distribution bars and tables: **Grouping_Rows** remains the visible category hierarchy, **Grouping_Columns** becomes the comparison series (with the final distribution level as its stack), and rows-only charts use one `(all)` series without duplicated labels. Campaign identifiers are display-normalized to `YYYY Qn` (for example, `UK_Q2_SA_2026` becomes `2026 Q2`) without altering their stored/filter values. **100% Stacked Vertical Bars** now preserve every hierarchy level and render row panes separately from nested column headers—for example, Call Family rows with Operator above Campaign columns—instead of flattening all dimensions into one axis label. **Count Stacked Horizontal Bars** use the same contract, rendering Call Family/G Level 4 as separate row levels and Operator/Campaign as nested column panels containing the Failed/Dropped counts.

#### 📚 Documentation:
- Replaced inherited and unrelated documentation, including the root-level roadmap, with a maintained numbered Dashboard Analytic Help set and embedded Help index.
- Expanded the README and numbered Help guides to document the current Workspace, CDR preview, Dashboard, persisted vendor mapping, reporting, catalogue conversion/editor and executable chart-grouping workflows.

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
