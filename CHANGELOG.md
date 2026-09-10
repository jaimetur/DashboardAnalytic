# 🗓️ CHANGELOG
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.2.3
### Release Date: 2026-09-10
#### ⚠️ Breaking Changes:

#### 🌟 New Features:
- Workspace duplication now asks whether to include generated Reports and Chart Sets, leaving that option unchecked by default; selected outputs copy the whole `output` tree and rebase their stored report paths, while imported workspaces likewise rebase copied report artifacts so Reporting can show their chart thumbnails immediately.
- Added global floating background-task panels on every authenticated page: active-workspace and server tasks appear at the lower right, while tasks belonging to other workspaces appear in a differently coloured lower-left panel headed by the workspace name; concurrent groups remain visible together with live progress until all work finishes.

#### 🚀 Enhancements:
- Added hover help to the interactive-tooltips option in Report and Chart Set generation confirmations, explaining that it enables chart-value context on pointer hover and adds a small generation-time cost.
- Added a blue Open workspace action with the 📂 folder icon immediately after Save in Manage Workspaces, and clarified the Save tooltip as `Save workspace changes`.
- Workspace duplication completion now updates its row in place without reloading the page, preserving the open state of Manage Workspaces.
- Workspace deletion now runs in the background, appears in the lower-left task panel and removes only its table row on completion without reloading or collapsing Manage Workspaces.
- Split CDR ingestion from combined-table regeneration: a dataset now reaches `Ready` at 100% and refreshes the Datasets table before its combined CDR is rebuilt as a separately tracked background task with its own progress in the global task panel.
- Updated the Readme, Changelog and Help navigation badges to use clear page-specific labels and stronger contrast, and added matching active-workspace totals for Reports, Chart Sets and all Jobs to the E2E Reporting header and Reports and Charts Jobs cards.
- Increased the contrast of Collapse and Expand badges on white panels with a neutral grey background, border and text.
- Added confirmed `Stop Job` controls to the global background-task cards for accessible-workspace duplication, dataset processing, Report and Chart Set generation, Auto-calculated Field materialization, combined CDR recreation and single-workspace exports/imports. Stopped duplications clean partial files and registry/access rows, stopped materializations retain a red status, stopped exports remove temporary files, and an import cannot be stopped once it has started.
- Replaced the stop glyph with a centered 0.56rem white square inside the circular `Stop Job` control, preserving the button dimensions and making its size consistent across browsers.
- Moved bulk deletion of all Reports and all Chart Sets into workspace background tasks with live progress in the global task panels; Reporting remains available and refreshes its job tables when each deletion completes.
- Kept the Open and Remove workspace actions disabled for the active workspace after its row is refreshed following background duplication.
- Added a Database Backups subpanel in Admin > Database Management with visually consistent **On demand backup** and **Scheduled backups** sections. On demand backup has side-by-side **Backup** and **Restore** panels: Backup creates a tracked ZIP from clearly labelled Configuration Content or Workspace Content, including Application database, Full workspaces, Slides Templates and Auto-calculated Fields, and reveals an accessible-workspaces multi-select with matching Backup content styling whenever workspace content is selected. Full workspaces includes the workspace database, templates and Auto-calculated Fields, disables the redundant template/field choices, and reveals a separate selector for optional Input raw datasets and Output reports/Chart Sets. Each ZIP records its selected components and full-workspace options in a versioned manifest; Restore uses it, with a structural fallback for older ZIPs, to detect Full workspaces and disable redundant template/field choices in its overwrite confirmation. Restore lists ZIPs in the chosen server-visible path, detects their available components and affected workspace names, and requires a structured overwrite warning confirmation with individually selectable restore parts and a grey Cancel action. Each panel validates only its own inputs, so Backup Now never requires a Restore file. The Restore file list refreshes after immediate backups and periodically while Admin is open, covering scheduled backups too. Manual backup cards expose **Stop Job** to their owner; stopping removes the incomplete ZIP. Both operations appear in the floating task card and neither they nor saving scheduler settings reloads or moves the Admin page; **Save scheduler settings** posts to the scheduler endpoint correctly. Backup notices stay in Backup protection, including compatibility redirects from prior URLs; **Refresh table** now uses the same burgundy action colour as **Backup Now**. Backups skip stale workspace-registry entries without a workspace database and use each workspace's visible name rather than its internal ID for the archive tree, preventing phantom or misleading workspace folders. Its high-contrast hover state preserves the selected-content label. Default storage is `config/scheduled-backups`; a large container-visible directory browser can create folders without entering them and is restricted to the application `config` directory, with fixed professional Home and Up controls, uniform high-contrast folder rows and an independently scrolling directory list; the wide, styled multi-select picker keeps each content option on one line with left-aligned checkboxes; retention defaults to 30 backups; and recurrence shows only the applicable weekday/month-day field before execution time and retention.
- Reordered Manage Workspaces actions so Duplicate precedes Open, expanded the New workspace and Open workspace fields to 800px in desktop layouts with their actions kept alongside, and remove cancelled workspace duplications from the live table once their partial copy is cleaned up.
- Moved Database View Actions to the first sticky column so row actions remain visible while horizontally scrolling, and styled the row Save action in green.
- Renamed the Auto-calculated Fields workspace table from `calculated_dimensions` to `autocalculated_fields`, with an automatic data-preserving migration for existing workspace databases.

#### 🐛 Bug fixes:
- Fixed the Reporting Chart Preview header so Manage Auto-calculated Fields appears beside its red Close control; Escape now leaves active Auto-calculated Fields and filtered-dataset child dialogs open, closing the preview only when no child dialog is active.
- Matched the Auto-calculated Fields dialog's circular close control to the Chart Preview close button and styled its text Close control in red with white text; each field deletion control uses a thick white minus on muted burgundy.
- Made Slides Templates Editor chart image and data previews load the chosen CDR type from its materialized combined reporting table instead of concatenating every individual CDR table.
- Fixed Slides Templates Editor Chart Preview so every template filter value is displayed and retained in its Filter builder.
- Added a non-applying Close action beside the red Update Template button in Slides Templates Editor Chart Preview; updating now requires confirmation that the displayed chart's template row will receive the Interactive Preview values.
- Fixed Auto-calculated Fields managers so deleted and duplicated fields update the displayed list immediately, before background materialization; their compact dialog keeps its header, close control and bottom actions fixed while only long field-card lists scroll.
- Added compact-screen pagination to the Workspace Auto-calculated Fields definitions list.

#### 📚 Documentation:
- Documented Database Backups: scoped configuration/workspace and full-workspace content, accessible-workspace selection, on-demand and scheduled ZIPs, Restore content detection and overwrite confirmation, config-scoped directory and ZIP pickers, retention, Docker storage requirements and floating-task progress, plus workspace-grouped background-task cards and their confirmed Stop Job behaviour.

---

## Release: v0.2.2
### Release Date: 2026-09-07
#### ⚠️ Breaking Changes:
- Moved status-row inclusion out of the chart renderer and into explicit template filters such as `Test_Result IN (Completed, Dropped, Failed)`; update affected templates so their status-chart denominator remains visible and editable.
- Slides Templates now belong to individual workspaces, including the template registry and CSV files; Database Management exposes the registry as Slides Templates registry under Workspace Tables. A one-time migration corrects legacy workspace paths that still point into the project tree, copies the former shared library to every workspace that already existed, registers each copy in its own database, removes the obsolete global registry and legacy configuration library only after success, while newly created workspaces, including Default, start without templates.

#### 🌟 New Features:
- Added an Edit Slides Template action to the active Charts Panel, opening the exact generating template in a full editor modal without the template selector.
- Added manual Refresh and silent five-second polling to App Logs, preserving active filters and the Executed by selector's state and options; filters are faceted from every loaded row matching the other active filters, including compact-phone cards.
- Added a Cancel operation action to outgoing server-transfer progress, cooperatively stopping connection, approval waiting, export or transmission and cleaning temporary output.
- Added the NSA `Tableau Charts` Slides Template with one slide for each of the workbook's 86 individual chart worksheets, excluding dashboards and auxiliary sheets, plus `Tableau Dashboards` with the workbook's 20 dashboards and every chart arranged on its corresponding slide; preserved Tableau titles, filters, legends and row/column aggregations, translated categorical ratios, percentiles and auto-calculated fields such as vendor split, result groups, bandwidths, throughput buckets, first LTE ARFCN, TTFP ratio and historical eMOCN/NNS, and added native latitude/longitude Map and multi-KPI CDF chart types.

#### 🚀 Enhancements:
- Made incoming transfer approvals reliable across every super-admin page, expired stale pending offers after 15 minutes, reused equivalent retries, propagated terminal source cancellation to the destination, and respected standard HTTP/HTTPS ports when a complete destination URL is entered without an explicit port.
- Preserved every explicitly filtered `IN` category in hierarchical chart grids even when it has zero matching samples; rendered status bars without unpainted `Cutoff` remainders with Completed in green and Cutoff/Dropped/Failed in red shades; moved the Tableau templates' `100% Stacked Vertical Bars` dimensions to Columns; and rendered every aggregation as a visible nested level, with all Rows levels on the left, every Columns level except the last above the plot, only the last below it, and no repeated compound captions.
- Increased and strengthened chart titles, axis values and bar-value labels across the shared renderers, and rebuilt legends with larger bold captions, markers, line samples and spacing for reliable preview and report scaling.
- Normalised App Logs users to lowercase with case-insensitive filtering, recorded explicit successful/failed login outcomes, and limited UI auditing to meaningful operations with descriptive actions such as report or Chart Set generation.
- Automatically opened and scrolled to the Charts Panel when a newly queued or retried Report Job completes successfully, matching the existing Charts Job workflow.
- Preselected the two most recently uploaded processed CDRs of each Data, Voice and Speech type in E2E Reporting, falling back to the sole available dataset when only one exists, and restored two recent selections on return from Vendor Comparison when necessary.
- Reduced each CDR selector to its most recently uploaded selected dataset when switching to Vendor Comparison, without replacing an existing single selection.
- Clarified Chart Set audit stages as generation requested, rendering completed and published; App Logs retains the initiating user in `User` and identifies background execution as `system` in the new `Executed by` column.
- Accelerated repeated multi-platform Docker builds with a stable shared BuildKit cache and isolated Python dependencies from font/timezone package changes, preventing unnecessary slow ARM64 `pip` reinstalls.
- Unified the inactive Workspace, E2E Dashboard, E2E Reporting and Chart Builder tabs with the Chart Builder palette while preserving each module's existing active colour.
- Ordered Campaign aggregation values chronologically from the oldest to the newest across every shared chart renderer, independently of dataset ingestion order.
- Set the default server-transfer destination port to `7278` while respecting an explicit URL port; the dialog remembers the last destination and submits from either field with Enter.
- Standardised Vendor Comparison charts by automatically excluding Mixed and Other vendors, resolving template Operator filters from the materialised operator prefix, preserving full vendor identities in aggregations and legends, and ordering mapped vendors consistently while retaining chronological Campaign values; where Vendor is the primary aggregation, Ericsson uses green shades, Huawei red, NSN blue, Samsung purple, Mixed and Other yellow, and blank values grey.
- Reworked Slides Templates Editor as a shared 90%-viewport dialog opened from Admin template actions or the active Charts Panel, with its selected name in the title, footer and corner Close actions, a fixed action bar and table-only scrolling; the embedded editor uses a lightweight route and clear yellow change markers that reset after save.
- Invalidated the active workspace-size snapshot after dataset, report and Chart Set files are created, completed, retried or removed.
- Fitted CDF legends into six evenly spaced entries per row when positioned above or below the chart, preserved each series' colour and line thickness with clearer latest-campaign samples, and sized left/right legend lanes to avoid wasted space or axis overlap.
- Rendered Distribution chart bucket legends as the ordered, colour-matched bucket ranges used by the stacked bars instead of displaying the raw `Buckets` filter expression.
- Rendered `Threshold` legends as two colour-matched ranges derived from the configured value (`< threshold` and `≥ threshold`), matching the red and green stacked-chart segments.
- Moved incoming transfer offers from hidden package-directory JSON files into the global SQLite database shared by Docker workers, automatically migrating legacy files; per-source replacement is atomic, new requests supersede older unreviewed offers immediately, and startup self-repairs the offer table with actionable diagnostics.
- Made Database Management discover and group every global configuration and active-workspace table, exposing Application state, Server transfer offers, Users and the Slides Templates registry alongside workspace tables including `report_chart_jobs` as Chart Set jobs and `report_runs` as Generated Reports jobs.
- Accelerated every Interactive Preview by caching combined CDR frames and filter results separately, so presentation and aggregation edits no longer reload or refilter unchanged datasets; Chart Preview also retains each loaded interactive definition and prefetches adjacent charts during navigation, while superseded browser render requests are cancelled and ignored.
- Unified Reports Jobs and Charts Jobs in one chronologically ordered panel and one physical `generated_jobs` workspace table, automatically migrating and removing the two legacy job tables; the panel includes explicit Tech and job Type columns, concise shared job metadata, a compact Progress column, each job type's original actions wrapped within their available cell, a combined count and both bulk-delete controls.
- Kept workspace sizes synchronized across the active-workspace header badge, header switcher and Workspace Management controls after background or AJAX file changes, and made the username badge an explicit hoverable keyboard-accessible change-password button.
- Made Readme the default selected tab after signing in or opening the authenticated application root.
- Renamed the Workspace queue heading to Datasets and replaced dataset, user, template and database row actions with compact circular icon controls carrying accessible hover labels and clearer download symbols, preserving those icon controls throughout live queued, processing, ready, failed and stopped transitions.
- Consolidated the 390×844 compact-phone layout across every module with a single-line login title and compact three-card feature summary, tighter panels, forms, non-overflowing protected-role labels and Export / Import controls; responsive cards for Users, Slides Templates, Reports and Charts Jobs, Datasets, Workspaces, transfers, App Logs and dynamic Database Management rows; labels above values, up to three short fields per row, paired dates, full-width IDs and left-aligned action rows; reliably visible Manage Workspaces content; and viewport-fitted chart, data and Slides Template editors with narrow action and slide columns, compact fixed controls, vertically stacked row actions, table-only scrolling and iOS-safe editable font sizes that prevent focus zoom.
- Paginated compact-phone card tables and Chart Set thumbnails to one visible item per page with compact icon-based First, Previous, Next and Last controls, thicker previous/next arrows, a centred page indicator above the controls, and automatic updates after live table refreshes, active filters and generated chart updates; filtering opens the first matching card, while App Logs preserves the selected card during manual or automatic refreshes and explicitly hides non-matches before pagination.
- Made workspace duplication preserve source access membership, defer reporting-row synchronization until required, complete in a background worker, clean interrupted partial copies through authorised workspace-admin actions, and redirect accidental GET requests to the POST-only operation.
- Reworked Chart Preview with a taller desktop dialog and a viewport-fitted mobile-landscape canvas: smaller, thicker chart navigation and header actions preserve the portrait layout; magnifying-glass zoom controls and boundary-aware overlaid pan arrows move the viewport in their labelled direction; report and Chart Set confirmation dialogs enable precomputed semantic tooltips by default but can omit them entirely, and enabled sidecars are versioned and written directly beside their PNGs in the final generation so obsolete hit-area geometry is regenerated on first use, while CDF hit testing is capped at 120 evenly spaced points per series and uses one reusable background worker for faster, smaller jobs; stale legacy staging directories are cleaned and Interactive Preview inspects only the selected datasets' schemas and explicitly identifies empty Rows, Columns and Filters selections; its new `Edit Template` action resolves the generating row through the editor's slide ordering and opens the originating Slides Template directly on that exact chart; targets use the renderer's exact CDF geometry and series identity to identify the line under the pointer, cover horizontal as well as vertical stacked-bar segments with their labels, values and legends after chart changes, zooming or panning; and the canvas repaints after mobile rotation while preserving zoom.
- Added native hover labels and accessible names to compact table action icons, strengthened the download arrows in Reports and Charts Jobs, and represented report downloads with a PPT presentation icon and explicit `Download PPT Report` tooltip beneath the green download arrow.
- Refined Workspace, Dataset and Slides Templates management tables with compact labelled actions, clearer Dashboard and chart glyphs, balanced metadata columns, readable date/time lines and flexible names without horizontal overflow.
- Ordered the combined Chart Set selector from newest to oldest across Report and standalone Chart Sets, and automatically select the newest available set regardless of its type.
- Allowed a CDR uploaded in a multi-file Workspace batch to select a VFUK or 3UK Vendor Mapping from the same batch; mappings are queued and processed before their dependent CDRs, while the upload dialog now distinguishes file transfer from the continuing background processing queue.
- Prefixed generated PowerPoint report names and their dedicated output folders with the creation timestamp for chronological filesystem ordering.
- Kept Reports and Charts job action buttons on a single compact row while fitting the tables to their available width without horizontal scrolling; preserved readable minimum widths for ID, Generated by, Date, Tech, Type and Progress, and gave Slides, Charts and Datasets additional space, while wrapping other long metadata within its cells and keeping the compact mobile card layout unchanged.
- Allowed PowerPoint Report and Chart Set jobs to run from any non-empty combination of Data, Voice and Speech CDRs, rendering an explicit unavailable-source placeholder for chart types without a selected CDR; added synchronized Tech, Type, Template and Scope filters to the Charts Panel selector and combined Jobs table, with Template choices retaining their registered capitalization and compact-phone job cards updating to the first matching page.
- Split Slides Templates Editor controls into non-fixed per-chart actions and block-level Slide Actions, with move, insert and delete controls consistently grouped on the first action row, constrained chart reordering, whole-slide movement/insertion/deletion, in-place duplication and chart/slide copying to a selected destination; selected dropdown values stay at the top and unsaved values and edited-cell highlighting survive table rebuilds.
- Refined workspace-owned Auto-calculated Fields management from Workspace, Slides Templates Editor and Chart Preview: the Chart Preview action now sits immediately beside Close, its wider dialog aligns its fields, compacts redundant case-only field aliases, documents case-insensitive matching, and uses a compact multi-choice Available for popover that closes after pointer exit or an outside interaction. The manager separates its Add action from the definition list, removes the editor Cancel action, provides a grey Close action beside Add or Save, keeps delete confirmations above the manager, replaces the minus deletion glyph with a cross, and adds distinct duplicate and purple download actions. Every save requires confirmation before rematerializing applicable CDR tables, and a rename also updates every Slides Template reference to that field.
- Reworked the Workspace Auto-calculated Fields panel with equal-width import and bounded, scrollable definition subpanels after Datasets, Field and Applied to column labels, matching Manage and green Export All Auto-calculated Fields actions, a Choose JSON filename display, a flexible full-width filename field, and an Import action aligned in one row with a distinct filename background. Imports confirm the operation and warn before overwriting existing fields, listing each overwritten field on its own bold bullet line. The Materialization status panel offers a small circular green relaunch action, confirms full rematerialization, displays the current percentage over the progress bar, and uses a pastel yellow background while materialization is in progress. The Datasets panel now lists existing combined CDR tables at the bottom as `CDR-Data (combined)`, `CDR-Voice (combined)` or `CDR-Speech (combined)`, includes their row counts and Updated date, participates in the matching CDR type filter, and provides a Preview dataset action followed by a confirmed circular background Recreate action. A combined table whose rows differ from the sum of its ready individual CDRs shows an orange `Missing Rows` status; each Preview verifies it again and warns that it can be recreated from Workspace > Datasets before allowing the incomplete table to open. Combined previews reuse the individual CDR preview template, filters and column colours, open in their own tab, and recreation updates both the combined-row status/progress and Materialization status with the live percentage; it also recovers inconsistent empty individual row stores from their source workbooks, validates every contributed row count and refreshes Workspace after completion. The management and slide re-enumeration buttons use the shared yellow gradient.
- Restricted Result Group, Call Family, Test Family and other Auto-calculated Fields to their applicable individual and combined CDR tables, removed stale out-of-scope calculated columns during rematerialization, highlighted generated columns pastel red in CDR Preview, exposed them only in applicable dataset-field selectors without delaying Workspace rendering, and migrated and removed former per-template JSON sidecars.
- Added Auto-calculated Fields export, import and transfer as portable ZIP packages through Export / Import, with multi-workspace destination selection on manual import and incoming transfer acceptance, preselecting the source workspace by name when it exists and leaving other destinations optional.
- Kept known empty metrics visible but disabled in Workspace selectors, made workspace duplication completion consistent with its asynchronous workflow, and relocated imported database paths for both direct moves and cross-volume copies.
- Saving, editing, deleting, JSON importing and full rematerialization now return immediately while a per-workspace background job reconciles every ready dataset into its combined CDR table before applying incremental in-place SQLite column updates to affected individual and existing combined tables, creates missing combined tables from the updated individual data when required, and preserves the preview filter columns, every source dependency used by applicable field rules and the resulting Auto-calculated Fields. It normally scans each affected table once instead of loading and replacing it through pandas, handles applicable tables without the source columns of a rule by using the field fallback, reports table-level progress and separate individual/combined table totals in the Workspace panel, and notifies the browser on completion. Identical imports are merged by normalized field name without duplicate definitions or materialized columns.
- Included workspace-owned Slides Templates in workspace exports and duplication while retaining standalone ZIP export and server transfer. Portable packages identify their source workspace by name; manual import and incoming transfer acceptance preselect the matching destination when present and allow additional workspace selections with access checks. Template import does not rematerialize CDR data: preview filters and auto-field dependencies are prepared eagerly, while other chart columns remain materialized on demand. Background Chart Set jobs resolve templates and auto-fields from their originating workspace.

#### 🐛 Bug fixes:
- Fixed Interactive Preview legend positions so title-case selector values such as `Left` are normalised before rendering instead of falling back to the right-hand side.
- Fixed CDR reporting accuracy by skipping leading ranking/helper worksheets between `KPI Definition` and the contiguous operator block, dynamically keeping each market's canonical operator sheet over technology variants, excluding trailing helper sheets such as `Lists` and `TMP_CLIPBOARD`, and retaining every Data attempt before explicit template filters; Voice and Speech imports now recognise numeric values stored as text and remain usable with an attempt-count fallback when no measured KPI is present. NSA/SA call-mode classification remains limited to Voice and Speech, with native and MultiRAB calls classified through VoLTE, EPSFB or VoNR before RAT fallback while WhatsApp uses its explicit RAT. Fixed horizontally shifted failure-chart tooltips by deriving their hit areas from the same full-width plot geometry as the renderer, aligned nested status-chart tooltip axes with their renderer so Tableau's vendor-split and geographic success-ratio charts no longer fail, invalidated obsolete stored targets automatically, and retained one map-point colour key per filtered row. Removed the internal batch-upload suffix from mapping choices.
- Made failed Report and Chart Set jobs expose their stored error directly in the Jobs table and record a readable Error event in App Logs, including jobs interrupted by an application restart.
- Fixed Docker source-layer freshness by keying application layers to the exact Git commit while retaining dependency caching, and embedded the revision in every published image for verification.
- Fixed undersized, non-bold Docker chart text by installing an Arial-compatible Linux font and sharing cross-platform font resolution across chart and export renderers.
- Excluded null, NaN and empty status/KPI values from both the numerator and denominator of 100% stacked charts instead of misclassifying them as failures or valid quality samples.
- Allowed admins to export or transfer their active workspace’s Slides Templates and only their accessible workspaces, while keeping configuration/full-environment transfers and workspace imports restricted; Workspace and Full Environment confirmations include generated reports and Chart Sets by default but can omit their files and job metadata, with the Full Environment workspace selector exposing that choice directly, removed forbidden options from their selector so transfer requests always include a valid target, made the initial destination handshake retry-safe and idempotent, persisted incoming offers, and made destination notification polling resilient to stale Docker-rendered pages and browser tab suspension.
- Rejected malformed Slides Template filters when adjacent conditions are missing their semicolon separator, located errors as `Slide: n - Chart: n`, validated manual filter-cell edits live with a self-updating warning, kept damaged templates open for correction, and stored each condition on its own line with editor-only bullet markers and quoted multiline CSV fields.
- Fixed the shared Legend contract across every chart renderer: an empty field suppresses the legend, a selected chart KPI/dimension shows its actual plotted values with exactly the same stable colour as its bars or lines even across nested campaign series, and a filter-only field shows the applied filter values as text; CDF legend samples also reproduce each curve's colour and historical/latest line thickness, while legacy slash-separated captions and Legend Position remain supported.
- Prevented dataset renames from rendering and downloading the complete Admin page after updating the file and materialised references, returning only the renamed dataset metadata to avoid intermittent gateway timeouts.
- Prevented normal admins from focusing or editing super-admin role controls by rendering the protected role as static text.
- Fixed Slides Template CSV exports so legacy manual filter/caption text does not incorrectly block downloading a template.
- Fixed application startup failures caused by SQLite `database is locked` errors when an existing worker held a database while another process attempted to reset its journal mode.
- Prevented startup from scanning, migrating and checkpointing every workspace database; only the active workspace is now recovered at launch, while other workspaces are handled when opened.
- Fixed the compact-phone Manage Workspaces disclosure by moving it out of the parent action layout, retaining the native open `details` layout required by Mobile Safari and rendering its workspace table as readable cards.
- Restricted Reporting deletion actions and endpoints to admins and super-admins, including live Jobs updates, and prevented touch interactions from triggering the Chart Set picker's mouse-leave close timer.

#### 📚 Documentation:
- Reorganised and rewrote the complete documentation for the current product: kept README as a concise introduction, module summary and deployment guide; added numbered Product Overview, Technical Considerations and dedicated Chart Builder articles; renamed the Data Ingestion guide to Workspace Management with a dedicated Data Ingestion section; renumbered the focused Help guides; and replaced long prose with structured workflows, bullets, examples, validation checklists and troubleshooting guidance.
- Added the dedicated Chart Builder guide immediately after E2E Reporting in Help, with examples for CDR Type, multi-dataset selection, Interactive Preview, ordered aggregations and Filter Builder troubleshooting.
- Updated the README and Help centre for workspace-owned Slides Templates and their migration/export/import/transfer behaviour, Auto-calculated Field authoring and background materialization, combined CDR previews and recreation, and the Slides Templates registry in Database Management.

---

## Release: v0.2.1
### Release Date: 2026-09-03
#### 🌟 New Features:
- Added persistent Charts Jobs alongside Reports Jobs, with progress, retry, cancellation, confirmed relaunch, ZIP downloads, bulk actions, job counts and direct opening of the generated Chart Set.
- Added a Multivendor multi-campaign review before report or Chart Set generation, requiring Data, Voice and Speech CDR selection and preselecting the latest campaign for each type.
- Added a shared Interactive Chart Preview and Chart Builder for E2E Reporting and Slides Templates Editor: editable chart settings regenerate temporary charts, a full-size filtered-dataset overlay provides Excel-style filters and pagination, and Update Template applies preview values to the in-memory row for normal saving.
- Added approved server-to-server configuration transfers: the source connects to a destination URL and port, waits for destination super-admin acceptance, streams the selected export and triggers its automatic disk-backed import on receipt.

#### 🚀 Enhancements:
- Consolidated Report Charts as the Charts Panel: it stores report-rendered PNGs under `output/reports/<report-name>/report-charts/` and standalone sets under `output/charts/`, uses scope-aware filenames and source styling, orders reports first, hides incomplete sets, standardises timestamps and refreshes or falls back after deletion or relaunch.
- Improved hierarchical, stacked and CDF charts by retaining every aggregation combination including zero-count values, adding relevant group separators, stable caption/axis and vendor styling, consistent campaign emphasis, non-overlapping labels and compact legends with conservative CDF axis trimming.
- Made Slides Templates saves asynchronous and atomic, and streamlined template selection, import and Cell Assistance with save/discard and overwrite flows, exact names, searchable compact controls, valid preselection and multi-value Filter Builder clauses.
- Refined Interactive Preview into a wide-screen chart/editor layout with a source-aware Filter Builder and searchable multi-select controls for Rows, Columns and Legend.
- Improved Interactive Preview controls by moving View filtered dataset to the chart navigation, renaming CDR Source to CDR Type, adding prefilled type-filtered dataset selection and correctly serialising multi-selected dataset IDs.
- Optimised configuration and workspace transfers with compact SQLite snapshots, disk-backed background imports, faster ZIP compression and extraction, workspace-scoped Full Environment exports, byte-level progress, live cross-server status, resilient incoming-package recovery and safe staged replacement imports.
- Renamed the bootstrap workspace to `Default`, migrating existing display names and storage paths without changing workspace data.
- Published native `linux/amd64` and `linux/arm64` Docker manifests and enabled GitHub Actions layer caching for faster image releases.
- Standardised campaign and UK operator labels, and deduplicated equivalent display and physical fields in Interactive Preview selectors.
- Renamed `E2E PowerPoint Reporting` to `E2E Reporting` and `E2E Dashboard Analysis` to `E2E Dashboard`.

#### 🐛 Bug fixes:
- Fixed Reporting CDR multi-select checkmarks after Multivendor review so they match the submitted CDRs.
- Fixed Report Charts failures to return actionable JSON errors and record Error events in App Logs.
- Fixed Chart Set and report deletion routing, dialogs, bulk cleanup and selector refreshes, including stale completed jobs and deleted folders after a single-set or all-set operation.
- Fixed the Docker workflow so `tag:latest` is always updated.
- Fixed Slides Templates Editor picker/registry state and prevented unregistered library CSVs appearing as phantom templates.
- Fixed Cell Assistance menu visibility, Jobs relaunch/row reuse and Reports Jobs table width.
- Fixed incomplete or empty Chart Sets and PowerPoint charts on constrained servers by serialising workspace rendering, streaming sources and PNGs, preserving template order, rebuilding frames before retry and logging isolated placeholders.
- Ensured the default `super`, `admin` and `demo` accounts always retain access to the `Default` workspace, including after startup migrations or access edits.
- Made incoming server-transfer approval available across every super-admin page and idempotent, preventing duplicate polling from reporting an already accepted offer as missing.
- Made large ZIP imports stream directly to their retained disk file and added byte-accurate browser upload progress, avoiding the previous multipart staging copy.
- Fixed Full Environment imports to translate source workspace IDs to their retained or newly created destination IDs, preserving every imported user permission even when the replaced workspace was open or had a different local ID.
- Fixed shared reporting-table reuse to detect and rebuild any chart-requested column that contains source data but is empty in one dataset's cached rows, preventing fields such as `G Level 4` disappearing from historical campaigns.
- Fixed newly added Filter Builder conditions so their Column and Operator controls immediately use the standard searchable selectors.

#### 📚 Documentation:
- Rewrote the PowerPoint Reporting help as static guidance for building Slides Templates, including field-by-field instructions and practical recipes for every chart type, filters, aggregations, legends, structural slides, operators and output jobs.

---

## Release: v0.2.0
### Release Date: 2026-08-31
#### ⚠️ Breaking Changes:
- Removed obsolete `config/app.db` and legacy workspace copies of global tables; `config/application.db` is the sole global configuration database.

#### 🌟 New Features:
- Added modular Workspace, Dashboard and PowerPoint Reporting areas, including the Smart Orchestrator Logs reporting entry point and dedicated Workspace, Dashboard, Reporting and Admin panels.
- Added Data, Voice and Speech CDR ingestion with VFUK/3UK vendor mapping and review queues.
- Added template-driven NSA/SA, multivendor and multi-campaign CDR-comparison PowerPoint reporting across Data, Voice and Speech.
- Added shared Slides Templates Management and Editor with import, export, defaults, duplication, deletion and blank-template creation ready for direct editing.
- Added independent workspace lifecycle management: create, open, close, rename, duplicate and remove.
- Added Database Management for browsing, editing and deleting records, with paginated Excel-style column filters.
- Added Import/Export ZIP packages for configuration, Slides Templates, individual workspaces and full environments.
- Restricted configuration and workspace Import/Export to `super-admin`; `admin` users can transfer only shared Slides Templates.
- Added global user, role and workspace-access administration, including the `super-admin` role.
- Added self-service password changes from the header User badge.
- Added processed-dataset preview, direct Preview/Show Dashboard actions and persistent Generated Reports Jobs with progress, metadata, Download and Delete actions.
- Added a dedicated App Logs tab with up to 1,000 operational and audit events plus persistent user, date, type and action filters.
- Added Report Charts to render every automated chart in a selected report template without creating a PowerPoint file, and persist the result as selectable timestamped workspace sets with scope-aware deletion, source counts and an enlarged viewer.

#### 🚀 Enhancements:
- Added root-level `storage-paths.conf` with `APP_CONFIG_DIR`, `APP_DATA_DIR` and `APP_ASSETS_DIR` overrides.
- Consolidated global users and Slides Template registry data in `config/application.db`, and moved templates, workspace databases, reports and registry files to dedicated configuration/data locations.
- Expanded and improved Slides Templates with chart titles, filters, row/column aggregations, legends and `Legend Position`; ordered multi-chart slides, preserved complete CSV data, added reusable layouts, per-chart previews, Cell Assistance, contextual help, searchable selectors and row insertion.
- Optimised repeated CDR reports with shared materialised tables and report-specific column loading.
- Improved Dashboard and preview performance, adaptive filters, vendor persistence, large-dataset handling and Excel-like CDR pre-filters; added safe dataset renaming, orphaned combined-CDR cleanup and colour cues for preview fields.
- Improved PowerPoint readability, hierarchical grouping, campaign-weighted CDFs and configurable legend placement.
- Made imports, exports, large ZIP transfers and report generation disk-backed background jobs with progress, overwrite warnings, session-independent execution and expanded report metadata/actions.
- Improved user administration with searchable workspace-access pickers, automatic validated saves, password masking/reset controls and role-labelled default access.
- Improved Database Management labels by separating Config Tables from Workspace Tables.
- Mark interrupted dataset-processing and report-generation jobs as retryable failures after an application restart, with Report Job retry actions.
- Added Created and Last Updated timestamps plus direct Edit actions to the Slides Templates Library, standardised its HTTP routes on `report-templates`, and renamed template audit-log terminology from `catalogue` to `template`.
- Kept the current module open when switching the active workspace from the header.
- Serialised dataset processing per workspace so retries wait as queued work while another dataset is processing.
- Materialised `Call Family` and `Test Family` as inspectable CDR dimensions with derived-field preview styling.
- Made Reporting panels collapsible with a NetCheck/Smart Orchestrator module selector, unified PowerPoint and Report Charts rendering, and improved hierarchy labels, title gutters and dense failure-chart readability.

#### 🐛 Bug fixes:
- Preserved chart-definition values during template migration, normalisation, sorting and visual merging, including defaults, renames, deletion protection, editor selection and report placeholders.
- Fixed CDR ingestion and mapping for duplicate headers, alternate encodings, Cell ID variants and vendor fields; failed mappings no longer hide datasets and failed imports can recover.
- Fixed dataset queue ownership, upload/update dates and background processing when a workspace closes or a user logs out.
- Fixed Dashboard filter restoration, cache invalidation, empty states and mobile document overflow.
- Fixed report generation for missing sources, empty tables, duplicate columns, mixed encodings and legacy metadata; child campaign bars now remain nested under their operator.
- Fixed report-job file discovery and historical-job loading after the move to `output/reports/`, and prevented obsolete workspace `exports/` directories from being recreated.
- Fixed Docker packaging of the master PowerPoint template, host-specific storage paths and local-time handling through `TZ` (default `Europe/Madrid`) across queues, profiles, logs, users, workspaces and report jobs.
- Fixed Admin loading with no active workspace or default template.
- Prevented stale SQLite sidecars and obsolete user records from overriding configuration imports; users, roles, IDs and workspace access now restore exactly.
- Fixed case-insensitive usernames across login, password changes and workspace access, including case-only duplicate prevention and a clear warning for unauthorised workspace login.
- Enforced workspace-access and super-admin safeguards: only super-admins have implicit workspace access, protected roles cannot be altered by lower roles, and the last active super-admin cannot be removed, demoted or deactivated.
- Fixed workspace-access picker visibility, clipping, alignment and save synchronisation, and stopped Users tables showing browser-restored values after imports or navigation.
- Fixed blank Slides Templates so they open as an editable empty canvas, and fixed the editor selector to always show the template actually opened.
- Fixed queued dataset and report jobs after restarts, and deferred derived-field backfill of large workspaces until their first Preview or Reporting use.
- Fixed report materialisation of equivalent CDR headings and stale derived dimensions, legend overlap in hierarchical failure charts, and Generated Reports Jobs width while reports process.

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
- Delivered the initial Dashboard Analytic MVP: a FastAPI multi-user KPI analytics interface with CSV/XLSX ingestion, KPI scoring, CDF charts, report exports, Docker and GitHub Actions.
- Added automatic multi-sheet `.xlsm` CDR workbook processing, cached dataset profiles with status, progress, retry and source-file deduplication, and a global processing overlay.
- Added application branding, favicon support, role-labelled header user badges and an expanded Admin Identity panel with inline editing, activation and deletion.
- Added PowerPoint export for the full Visual Analytics dashboard state.

#### 🚀 Enhancements:
- Redesigned the dashboard with queue tables, right-side adaptive filters, collapsible panels, cached workspace metadata and on-demand analysis; dashboard analyses and workspace queries use cached/materialised data for faster refreshes.
- Refreshed the login and workspace UI, versioned CSS/JS assets, used published Docker Hub images in production compose, and replaced native deletion confirmation with a styled modal.
- Improved ingestion and queue workflows with multi-file chunked uploads, live and finer-grained processing progress, English upload labels, clearer action controls, dataset-size labels and the final `Data Processing` naming.
- Added multi-KPI and executive dashboard views, global KPI cards, date-range and City filters, multi-select adaptive filters, per-chart aggregation overrides and grouped executive metric panels.
- Persisted Workspace and Admin form, collapse and last-opened-dataset state in browser storage.
- Replaced native multi-select boxes with searchable dropdown controls and Select All / None.
- Added workspace logs with Info and Error filters, improved CDR-Speech/CDR-Data detection, and reduced PowerPoint export time by reusing cached files and condensing metric slides.
- Improved CDF rendering and exports with adaptive sampling, full multi-operator series, per-chart range sliders and practical default cutoffs, labelled axes and units, visible grids/ticks and correctly placed vertical labels.

#### 🐛 Bug fixes:
- Fixed account safeguards and visibility: default access reflects active default-password users, and the last active admin cannot be removed, deactivated or demoted.
- Fixed document image paths, workspace empty-state alignment, dataset type/selection filtering, upload submission, duplicate source headings and direct display of processing errors.
- Fixed Dashboard support for legacy ready datasets and header variations, including spaced and lowercase dimensions, non-ready workspace selection, date filters, aggregation independence and empty grouped-percentile fallbacks.
- Fixed Dashboard navigation and persistence so Workspace/Open, queue Open, dataset switching and app relaunch restore the target dataset's saved filters, Global CDF Comparison and Global Aggregation from the first render without default values overwriting them.
- Fixed legacy materialised-table refresh and Technology normalisation; the dashboard displays the stable `Technology` label while normalised data prioritises `RAT` for data datasets.
- Fixed bar-chart normalisation, PowerPoint KPI strips and data-filter ordering.

#### 📚 Documentation:
- Added Readme and Changelog navigation with a Markdown document viewer, the application logo in the README and links that open both documents in a new tab.
