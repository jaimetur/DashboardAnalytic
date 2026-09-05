# Technical considerations

This article collects rules that affect data interpretation, performance, persistence and generated output. Read it before comparing Dashboard Analytic with another analytical tool.

## Storage boundaries

Dashboard Analytic separates global configuration from workspace data.

### Global configuration

Stored below `APP_CONFIG_DIR`:

- `application.db`: users, roles, workspace permissions, template registry and server-transfer offers.
- `slides-templates/`: shared CSV Slides Templates.

### Workspace data

Stored below `APP_DATA_DIR/workspaces/<workspace>/`:

- `<workspace>.db`: datasets, profiles, audit events, generated jobs and materialised reporting rows.
- `input/`: uploaded source files.
- `output/reports/`: generated PowerPoint reports and their PNG charts.
- `output/charts/`: standalone Chart Sets.

The workspace registry is local to the deployment. Full Environment imports rebuild it from the imported workspaces instead of retaining source-server absolute paths.

## Processed and derived columns

The importer preserves source fields and adds normalised fields used across modules. Common examples include:

- `Campaign`, formatted as `yyyy-Qx` when year and quarter can be resolved.
- `Operator`, normalised for stable display and comparison.
- `vendor`, populated by the explicit vendor-mapping workflow.
- `Call Family`, derived from call/session mode.
- `Test Family`, derived from the available test type/name fields.
- `Rate Bucket`, calculated for distribution charts from configured bucket limits.

Derived preview columns are visually distinguished from source columns. They do not imply that the original workbook contained those headings.

## Operator normalisation

Report-facing operator aliases are resolved consistently without rewriting the source workbook.

- Vodafone spellings resolve to `VF`.
- Telefónica/O2 spellings resolve to `O2`.
- Three, `3` and `Three UK` resolve to `3`.
- Recognised EE spellings resolve to `EE`.

Normalisation is case-insensitive and avoids ambiguous fragments. For example, `H3G` is not treated as Three because it can refer to unrelated vendor/technology text.

## Technology selection

Technology filters inspect the available radio-access field, commonly `RAT`, `RAT_A` or `Sample_RAT_A`.

- NSA selects recognised ENDC/NSA samples.
- SA selects recognised NR/SA samples.
- Missing radio values are not silently assigned to a technology.

When a chart looks incomplete, compare its filtered dataset with the source fields before assuming that a visual category is missing.

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

When `Campaign` is used as an aggregation dimension, values are ordered chronologically from oldest to newest. Recognised forms such as `2026 Q2`, `2026-Q2` and year/quarter source fields resolve to the display form `2026-Q2`.

Example:

```text
2025-Q4 → 2026-Q1 → 2026-Q2
```

## Filter language

Each condition is joined with logical AND and ends with `;`.

```text
Test_Result IN (Completed, Dropped, Failed);
Operator IN (VF, 3, EE);
G Level 4 IN (Belfast, Bristol, Cardiff, Edinburgh, London, Leeds, Sheffield);
```

Supported forms include:

- Equality: `Direction = DL;`
- Inequality: `Operator != O2;`
- Lists: `Operator IN (VF, 3, EE);`
- Excluded lists: `vendor NOT IN (Mixed, Other);`
- Text matching: `Test_Name CONTAINS FDFS;`
- Excluded text: `vendor NOT CONTAINS (Mixed, Other);`
- Numeric comparisons: `LQ >= 1.6;`

The Filter Builder accepts comma-separated `IN` and `NOT IN` values with or without parentheses and adds the parentheses required by the parser. It renders one condition per line. The CSV stores the same newlines inside the quoted cell.

Missing semicolons between conditions are rejected. Errors identify the logical position in the template:

```text
Slide: 5 - Chart: 1 -> Invalid filter ...
```

## Ordered aggregations

Rows and Columns are ordered multi-selections. Selection order defines the hierarchy.

```text
Rows: Operator × Campaign
```

To create that expression, select `Operator` first and `Campaign` second. Reversing the order changes grouping, separators and labels.

- Rows define categories or table rows.
- Columns define comparison series or table columns.
- Complete aggregation combinations can be retained with zero counts where the chart contract requires aligned comparisons.

## Legend rules

The `Legend` field is interpreted from the chart definition.

- Blank: no legend is drawn.
- Aggregation/KPI dimension: show the values included in the chart.
- Filtered field: show the values applied by that filter as contextual text.
- `Threshold`: show coloured below/above-threshold keys and the configured threshold value.
- `Buckets`/`Rate Bucket`: show human-readable ranges derived from the bucket boundaries.

`Legend Position` accepts `Top`, `Bottom`, `Left` and `Right`. The renderer reserves plot space for side legends so they do not overlap the chart.

For CDF Lines, legend handles reproduce both series colour and relative line width. Campaign legends are compacted into multiple columns for top/bottom placement.

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

Resolution rules:

- Same first/last vendor → Vodafone plus that vendor.
- Different vendors → Mixed Vendor.
- Ericsson/null and other unresolved combinations follow the supplied Vodafone business rule and may resolve to Mixed Vendor or Other Vendor.

### Three mapping

3UK mappings use `Cid__ECI` or `CId___ECI` as the materialised `GCID`.

- Same first/last vendor → Three plus that vendor.
- Different or conflicting vendors → Mixed Vendor.

O2 and EE remain operator comparison values because this workflow has no corresponding multivendor mapping source for them.

### Remapping

Use **Clear Vendors** before applying a newer mapping. Mapping and clearing are background operations and can be applied to several CDRs.

For Vendor Comparison, the renderer also appends this effective filter without altering the stored template:

```text
vendor NOT CONTAINS (Mixed, Other);
```

## Interactive Preview caching

The shared Interactive Preview is used by E2E Reporting, Chart Builder and Slides Template editing.

Its cache separates expensive data work from presentation work:

- Dataset combination depends on selected datasets.
- Filtered rows depend on datasets, technology and filters.
- Aggregation depends on rows, columns, KPI and chart type.
- Presentation changes such as title or legend position reuse unchanged filtered data.
- Superseded browser requests are cancelled and ignored.

Changing only a title should therefore be much faster than changing datasets or filters.

## Filtered dataset preview

The filtered-data overlay uses the complete chart-filtered dataset, not a fixed first-200-row sample.

- Pages contain 100 rows.
- Page navigation is server-side and remains fixed outside table scrolling.
- Vertical and horizontal scrolling affect only the table viewport.
- Column-filter value lists are calculated from all chart-filtered rows.
- Counters distinguish total dataset rows, chart-filtered rows, rows after column filters and rows shown on the current page.

## Background jobs and output

Reports and standalone Chart Sets share the `generated_jobs` table and are distinguished by `job_type`.

- `report`: creates a PPTX and its report chart PNGs.
- `chart_set`: creates the standalone PNG collection.

Output locations:

```text
output/reports/<report-name>/
  <report-name>.pptx
  report-charts/

output/charts/<generation>/
```

Jobs continue after leaving the page or signing out. A process restart marks interrupted in-process jobs as failed and retryable because the current worker model runs inside the application process.

## Import, export and server transfer

Portable ZIPs can contain configuration, templates, workspaces or a selected Full Environment.

- Large packages are built and processed on disk rather than fully in browser memory.
- Workspace database snapshots use SQLite-safe copy/backup behaviour.
- Workspace replacement closes the target automatically when required.
- Old workspace files are removed only after the replacement succeeds.
- Full Environment import preserves imported workspace permissions, including the workspace that was active on the source.

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
- Dashboard analysis is on demand and cached by dataset/filter/metric context.
- Interactive Preview caches combined and filtered frames separately.
- Database import prefers bulk database/file replacement over row-by-row queries where safe.

SQLite suits the current deployment model, but very large concurrent installations may eventually require an external database and worker queue.
