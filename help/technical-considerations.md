# Technical considerations

This article collects rules that affect data interpretation, performance, persistence and generated output. Read it before comparing DriveTest Analyzer with another analytical tool.

> [!IMPORTANT]
> **Source values and presentation.** Stored source values and the labels the tool shows are different layers. Operators, Vendors and Campaigns are shown everywhere with their Operator, Vendor and Campaign Maps labels, and a mapped selection matches every source spelling; only Preview Dataset shows the source values. The maps never rewrite uploaded workbooks or stored CDR values.

> [!NOTE]
> **Compare equivalent selections.** Match CDRs, NR Mode, filters, aggregation levels and missing-value rules before comparing results with another tool.

> [!TIP]
> **Caches and backups.** Caches accelerate views and can be rebuilt. Preserve databases and raw input when a recoverable backup is required.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Storage boundaries | [Open section](#storage-boundaries) |
| Processed and derived columns | [Open section](#processed-and-derived-columns) |
| Operator normalisation | [Open section](#operator-normalisation) |
| NR Mode and radio-access selection | [Open section](#nr-mode-and-radio-access-selection) |
| Test result semantics | [Open section](#test-result-semantics) |
| Campaign ordering | [Open section](#campaign-ordering) |
| Template execution semantics | [Open section](#template-execution-semantics) |
| Multivendor calculation and remapping | [Open section](#multivendor-calculation-and-remapping) |
| Interactive previews and Dashboard preparation | [Open section](#interactive-previews-and-dashboard-preparation) |
| Filtered dataset preview | [Open section](#filtered-dataset-preview) |
| Background jobs and output | [Open section](#background-jobs-and-output) |
| Import, export and server transfer | [Open section](#import-export-and-server-transfer) |
| Performance and scale | [Open section](#performance-and-scale) |

## Storage boundaries

DriveTest Analyzer separates global configuration from workspace data.

### Global configuration

Stored below `APP_CONFIG_DIR`:

- `application.db`: users, roles, workspace permissions and server-transfer offers.

### Workspace data

Stored below `APP_DATA_DIR/workspaces/<workspace>/`:

- `<workspace>.db`: datasets, profiles, audit events, Dashboard definitions and selections, generated jobs, Auto-calculated Fields, complete Report Templates in `report_templates`, and materialised reporting rows.
- `input/`: uploaded source files.
- `output/reports/dashboards/`: Dashboard PowerPoint jobs and their persistent PNG, tooltip and Canvas-model assets.
- `output/reports/cdr-analysis/`: CDR Analysis PowerPoint and Word exports.
- `output/reports/network-insights/`: Summary Network Insights PowerPoint and Word exports.
- `output/reports/reports-old/`: Reporting (old) PowerPoint reports and their PNG charts.
- `output/reports/reports-charts-old/`: Reporting (old) Chart Sets.
- `output/reports/reporting-jobs/`: Reporting Job runs, one folder per run with its artifacts.
- `.dashboard-data-cache/`: regenerable E2E Dashboard preview manifests and live Canvas/legacy PIL chart artifacts. Dashboard SQL reads the combined CDR tables in the workspace database directly; this directory is not a user dataset or source of record.
- `.dashboard-cache-version.json`: signature used to invalidate caches written by older application or cache-format versions.

Workspaces, backups and transfer packages created with the former layout (module folders directly below `output/` and loose documents in `output/reports/`) are moved to these folders the first time the workspace is opened, and the job paths stored in the workspace database follow them.

Application-level derived data lives below `APP_DATA_DIR`: `transfer-packages/` holds temporary/recoverable portability archives, `scheduled-backups/` is the default Admin backup destination and `.map-tiles-cache/openstreetmap/` stores regenerable map tiles.

The workspace registry is local to the deployment. Full Environment imports rebuild it from the imported workspaces instead of retaining source-server absolute paths. Report Template import, export, backup and transfer packages use CSV as a portable representation; the live templates remain database-backed and current flows remove obsolete `slides-templates` directories. See [Project Structure → Persistent data layout](project-structure.md#persistent-data-layout) for the complete ownership tree.

## Processed and derived columns

The importer preserves source fields and adds normalised fields used across modules. Common examples include:

- `Campaign`, preserving source text; filters and chart labels present recognised values with the workspace [Campaign Maps](workspace-config.md#campaign-maps), by default as `YYYY-Qn`, `YYYY-Qn-NSA` or `YYYY-Qn-SA`.
- `Operator`, preserving source values; configured aliases supply canonical labels for charts and comparisons.
- `Operator_Vendor`, the `<Operator>_<Vendor>` identity populated by explicit vendor mapping (and `Vendor_Operator`, the same identity as `<Vendor>_<Operator>`, derived when the CDRs are read), and `Vendor`, which removes a recognised operator prefix for real vendors. Both store `Operator - All` for operators without an assigned vendor. Workspaces created before these names are migrated once at startup (`Vendor` → `Operator_Vendor`, `Vendor_Only` → `Vendor`), together with their stored filter values and Report Templates.
- `Call Family`, derived from call/session mode.
- `Test Family`, derived from the available test type/name fields.
- `Rate Bucket`, calculated for distribution charts from configured bucket limits.

Derived preview columns are visually distinguished from source columns. They do not imply that the original workbook contained those headings.

### Auto-calculated Fields and combined tables

Auto-calculated Fields are workspace definitions. A field has a name, selected source datasets, a fallback and either ordered case-insensitive `condition => result` rules or a nested Tableau-style `IF / THEN / ELSEIF / ELSE / END` expression. It is materialised only in the individual and combined CDR tables for its selected sources.

The same parsed decision tree drives in-memory previews and parameterized SQLite materialization so nested-branch and fallback semantics remain identical.

Combined reporting tables are intentionally compact. They always retain reporting-core fields, Preview filter fields, source fields required by applicable Auto-calculated Field rules and resulting calculated fields. Other template-requested source fields are added lazily when a chart/report first requires them. This avoids eagerly copying every source column for every template, which would make imports and template changes unnecessarily expensive.

Materialization and combined-table recreation run in background jobs. Recreate rebuilds a CDR type from its ready individual datasets, reloads an inconsistent individual store from its source file when available, and verifies both per-dataset and total counts.

## Operator normalisation

Report-facing operator aliases are resolved consistently without rewriting the source workbook.

- Vodafone spellings resolve to `VF`.
- Telefónica/O2 spellings resolve to `O2`.
- Three, `3` and `Three UK` resolve to `3`.
- Recognised EE spellings resolve to `EE`.

Normalisation is case-insensitive and avoids ambiguous fragments. For example, `H3G` is not treated as Three because it can refer to unrelated vendor/technology text.

## NR Mode and radio-access selection

NSA/SA selection is a report or Dashboard-definition rule rather than a universal row-level RAT filter.

- Voice and Speech sessions are classified from the available RAT and Call Mode evidence. Recognised ENDC/NSA sessions enter NSA; recognised NR/SA sessions enter SA.
- Valid Data attempts remain available even when a sampled radio-access value records fallback. This prevents an otherwise valid data test from disappearing solely because one sample is LTE.
- E2E Dashboard does not expose Technology as an adaptive filter. Its NR Mode belongs to the Dashboard definition, while the separate RAT filter can restrict explicit `RAT_A`, `RAT` or `Sample_RAT_A` values.
- Missing radio values are not silently relabelled as a recognised technology.

When a chart looks incomplete, compare its chart-filtered dataset with the source RAT and Call Mode fields and with the selected NR Mode.

## Test result semantics

Charts must not treat every unknown result as a failure.

- Empty, null and NaN results are excluded from categorical result calculations.
- Template filters can explicitly restrict accepted states, for example:

```text
Test_Result IN (Completed, Dropped, Failed);
```

- Values outside that list, such as `Cutoff`, are excluded by the template rule rather than hardcoded globally.
- Conditions use the real field value after ordinary normalisation; substring accidents such as treating `Not Completed` as `Completed` must be avoided.

This design keeps the business rule visible in the template and makes comparisons with Tableau or another source reproducible.

## Campaign ordering

Every chart, table, legend and PowerPoint or Word report shows a campaign as its year and quarter, followed by its radio mode when it has one: **2026-Q2**, **2026-Q2-NSA** or **2026-Q2-SA** (for example `UK_Q2_SA_2026`, `2026 Q2 SA` or `2026-Q2_SA` all read `2026-Q2-SA`). Values without a year and quarter are shown as they are. Filters keep the full campaign, and the Excel and CSV exports keep the original values.

Campaigns are ordered chronologically from oldest to newest; inside a quarter, the campaign without a mode comes first, then NSA, then SA. Values without a year and quarter come first, by name. These are the defaults: the label format, the order inside a quarter and exceptions for campaigns that do not follow the pattern are set per workspace in [Campaign Maps](workspace-config.md#campaign-maps).

Example:

```text
2025-Q4 → 2026-Q1 → 2026-Q2 → 2026-Q2-NSA → 2026-Q2-SA
```

## Template execution semantics

Template filters are parsed as ordered, semicolon-terminated conditions joined with logical AND. Rows and Columns are ordered dimensions, so reversing their selection changes the grouping hierarchy. Legends derive their content from the chosen dimension, filter, threshold or bucket rule, and side legends reserve plot space.

These contracts are shared by E2E Dashboards, Reporting (old), Chart Builder and Template Editor so a saved definition has the same meaning in previews and generated output. The authoring syntax, operators, examples, aggregation behaviour and legend rules are centralized in [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

## Multivendor calculation and remapping

Vendor mapping is performed explicitly in Workspace and stored on the CDR before Vendor Comparison is enabled.

### CDR lookup key

The mapping logic takes the first and last usable Global Cell ID from available fields such as:

- `Cell_ID_A`
- `Cell_IDs_A`
- `Cell_ID`
- `Global CI`
- `GCID`, `GCI`, `CGI` or `ECI`

Case and separator variations are accepted.

### Vodafone mapping

VFUK mappings materialise `GCID` as:

- 4G: `eNodeB ID × 256 + Local Cell ID`
- 5G: `gNodeB ID × 4096 + Local Cell ID`

### Three mapping

3UK mappings use `Cid__ECI` or `CId___ECI` as the materialised `GCID`.

### Resolution rules

Every Vodafone Operator (any name starting with Vodafone or VF) uses the VFUK mapping and every Three Operator (any name starting with Three or 3) the 3UK mapping. Vodafone UK (`Vodafone_`), Three UK (`3_`) and the other spellings (their own name as prefix, for example `Vodafone VoNR_` or `VF_SA_`) resolve the first and last cell with the same rule, stored in `Operator_Vendor`:

- Same first/last vendor → `<Operator>_<Vendor>`.
- Ericsson at either end and a different or missing vendor at the other → `<Operator>_Ericsson_Mixed`.
- Any other different or missing combination → `<Operator>_Non-Ericsson_Mixed`.

O2 and EE store `<Operator> - All` because this workflow has no corresponding multivendor mapping source for them. `Vendor` keeps the vendor alone (`Ericsson`, `Ericsson_Mixed`, `Non-Ericsson_Mixed`) and `Vendor_Operator`, derived when the CDRs are read, the same identity as `<Vendor>_<Operator>`.

### Remapping

Map CDRs again to apply a newer mapping; the new result replaces the previous one without a prior Clear. Mapping and clearing are background operations and can be applied to several CDRs.

For Vendor Comparison, the renderer also appends this effective filter without altering the stored template:

```text
vendor NOT CONTAINS (Mixed, Other);
```

## Interactive previews and Dashboard preparation

Reporting (old), Chart Builder and Report Template Editor use the shared Interactive Preview. E2E Dashboards uses the same chart contracts in its live viewer, expanded viewer and historical Charts Panel, while preparing one synchronized dataset selection for the complete Dashboard.

Live charts draw their Canvas models in the user's browser. Server-side Report, Chart Set and Dashboard exports send those same models through a persistent Node/Chromium renderer, which keeps chart geometry and semantic tooltips aligned with the interactive view. Docker includes these runtime dependencies; source deployments using `dashboard-canvas` need Node.js, a supported Chromium-family browser and the WebSocket module.

`DRIVETEST_ANALYZER_CHROMIUM` can select an explicit browser executable, while `DRIVETEST_ANALYZER_REPORT_CHART_RENDERER=pil` selects the legacy painter.

The shared preview cache separates expensive data work from presentation work:

- Dataset combination depends on selected datasets.
- Filtered rows depend on datasets, technology and filters.
- Aggregation depends on rows, columns, KPI and chart type.
- Presentation changes such as title or legend position reuse unchanged filtered data.
- Superseded browser requests are cancelled and ignored.

Changing only a title should therefore be much faster than changing datasets or filters.

E2E Dashboard persistence has additional layers:

- `dashboard_filter_selections` stores a versioned selection key, faceted filter values and row counts; its predicates are reproduced from the saved Dashboard definition.
- The shared `reporting_rows_data`, `reporting_rows_voice` and `reporting_rows_speech` combined tables supply Dashboard filters, chart datasets and chart rendering directly.
- `.dashboard-data-cache/charts-canvas` stores compact interactive models; `charts-pil` contains legacy raster artifacts and `dashboard-previews` stores reusable preview manifests.
- Cache keys include selected datasets and revisions, NR Mode, scope, dates, filters, template definition and renderer/cache versions. Equivalent value and dataset ordering resolves to the same selection.

When a workspace opens, the application compares its saved cache signature with the current application and every Dashboard cache-format version. A mismatch deletes obsolete chart models, manifests and selection metadata, then records the current signature. Current-version artifacts remain available. The Workspace **Clear cache** action performs the same derived-data cleanup on demand without deleting definitions, datasets, combined CDR tables, templates or generated jobs.

Dashboard pre-caching (the automatic warm-up of each Dashboard's standard universes, described in [E2E Dashboards](e2e-dashboards.md#preparation-lifecycle-and-cache)) runs on a dedicated low-priority thread, separate from the shared background scheduler used by datasets and exports. It shares one Dashboard work slot with foreground preparations and exports, always yields to them, and prefers Dashboards open in a browser.

Chart models are generated only when the corresponding chart is viewed or included in a requested PPT.

The combined-table revision in these cache keys advances only when rows are inserted or rebuilt. Adding or filling columns (for example when another Dashboard or template needs a new field) records a separate timestamp and keeps every prepared universe valid.

Manage Dashboards status checks read each universe manifest directly from its fingerprint-derived path and are reused until datasets, combined rows, auto-calculated fields, mappings, templates or manifests change. Only the most recently used Dashboard snapshots keep their pandas chart frames in memory (3 by default, configurable with `DRIVETEST_ANALYZER_DASHBOARD_FRAME_CACHE_SNAPSHOTS`); older snapshots rebuild them from the combined tables on demand, which bounds memory use on smaller servers.

## Filtered dataset preview

The filtered-data overlay uses the complete chart-filtered dataset, not a fixed first-200-row sample.

Charts in the same Reporting Chart Set and CDR type share one cached source frame. Each chart then projects and filters only its own required columns, avoiding repeated reads of nearly identical source data while preserving chart-specific KPI and filter fields.

- Pages contain 100 rows.
- Page navigation is server-side and remains fixed outside table scrolling.
- Vertical and horizontal scrolling affect only the table viewport.
- Column-filter value lists are calculated from all chart-filtered rows.
- Counters distinguish total dataset rows, chart-filtered rows, rows after column filters and rows shown on the current page.

## Startup and workspace upgrades

At startup the server opens the active workspace in a background thread. A normal start finishes within a few seconds, as before; when the workspace database needs one-time upgrades after an update (for example the vendor column migration), the server starts answering after three seconds with a page that shows what is being prepared and opens the application as soon as it is ready. Until then every page answers `503` with that page and every API answers `503` with a JSON message; `/api/startup-status` reports the progress.

## Background jobs and output

Classic Reports and standalone Chart Sets share the `generated_jobs` table and are distinguished by `job_type`.

- `report`: creates a PPTX and its report chart PNGs.
- `chart_set`: creates the standalone PNG collection.

Output locations:

```text
output/reports/reports-old/<report-name>/
  <report-name>.pptx
  report-charts/

output/reports/reports-charts-old/<generation>/
```

Dashboard PowerPoint generations use the separate `dashboard_ppt_jobs` table because they preserve a saved Dashboard identity and its exact applied definition. Each job records its CDR selection, dates, NR Mode, scope, adaptive filters, preview fingerprint and progress. Its output contains the PPTX plus persistent PNG, tooltip and Canvas-model assets:

```text
output/reports/dashboards/<timestamp - dashboard-name>/
```

The Dashboard jobs UI supports stop, retry, relaunch and deletion. A completed job can be reopened through Charts Panel without rerendering its charts, and its Filtered Chart Dataset replays the saved selection directly against the combined CDR table used at generation time.

Both job families continue after leaving the page or signing out. A process restart marks interrupted in-process jobs as failed and retryable because the current worker model runs inside the application process.

## Import, export and server transfer

Portable ZIPs can contain Application Config, Dashboard definitions, Report Templates, Auto-calculated Fields, complete workspaces or a selected Full Environment.

- Large packages are built and processed on disk rather than fully in browser memory.
- Workspace database snapshots use SQLite-safe copy/backup behaviour.
- Backups write each database snapshot to a temporary `drivetest-analyzer-export-*` folder inside the backup folder and delete it when the snapshot is archived. Every finished backup also deletes snapshot folders left by backups that were killed mid-copy, once they have been unchanged for six hours.
- Workspace replacement closes the target automatically when required.
- Old workspace files are removed only after the replacement succeeds.
- Full Environment import preserves imported workspace permissions, including the workspace that was active on the source.
- Dashboard-only packages contain definitions and comments. Complete workspace and Full Environment packages can include source CDRs and generated output; regenerable Dashboard and map caches are never portability content.

Server transfers use a persisted offer and resumable package reception:

1. Source requests approval from the destination.
2. A destination super-admin accepts or rejects it from any page.
3. Source builds the package with progress.
4. Destination receives chunks with progress.
5. Completed reception starts import with progress.
6. Reloading either browser restores the active transfer state.

Incomplete transfer files are cleaned up. Complete packages that were not imported appear in the Admin recovery table.

## Performance and scale

- SQLite uses WAL mode, a busy timeout and normal synchronous mode.
- Processed CDR rows are materialised per dataset and into combined tables by CDR type.
- E2E Dashboard filter catalogues normally come from persisted dataset profiles. If an older profile lacks a current default or added field, the application reads only the missing catalogues from combined CDR tables in one grouped pass per CDR type.
- Combined CDR tables are queried directly and compact Canvas models persist across restarts after being requested. Live, expanded, historical and exported charts share aggregation, hierarchy, colour, title, legend and semantic-tooltip contracts with Reports and Chart Sets.
- Interactive Preview caches combined and filtered frames separately.
- Database import prefers bulk database/file replacement over row-by-row queries where safe.

SQLite suits the current deployment model, but very large concurrent installations may eventually require an external database and worker queue.
