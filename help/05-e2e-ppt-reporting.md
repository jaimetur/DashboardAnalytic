# 5. E2E PowerPoint Reporting

Dashboard Analytic supports a generic dashboard export and a template-backed NetCheck CDR report. The latter is available from **E2E PowerPoint Reporting → NetCheck CDR Reports**.

## Before generating a NetCheck report

Upload and process the required files in Workspace first:

- one or more `CDR-Data` workbooks;
- one or more `CDR-Voice` workbooks;
- one or more `CDR-Speech` workbooks.

The Reporting selectors default to the latest ready CDR of each type, but support multiple selection. Use Ctrl/Cmd-click to select additional workbooks. Selected Data, Voice and Speech CDRs are read from their respective shared reporting tables using the union of available columns, so repeated reports do not need to concatenate the original datasets again. Existing `Campaign` values are retained, enabling comparisons such as 2025 Q4, 2026 Q1 and 2026 Q2 in the same report.

Before the report applies template filters and groupings, it also consolidates recognised historical UK operator aliases in its in-memory data. Thus `Vodafone` and `Vodafone UK` appear as `Vodafone`; `O2(UK)` and `o2 - de` as `O2`; `3`, `Three` and `three(uk)` as `3`; and EE variants as `EE`. A template filter such as `Operator IN (Vodafone, O2, 3, EE)` therefore matches all of those variants. This is a report-only compatibility layer and does not rename any Workspace dataset.

For a Multivendor report, also process the relevant **VFUK Vodafone UK** and/or **3UK Three UK** mappings, then apply them while importing each CDR or use **Map Vendors** from the Workspace queue later. The reporting page no longer selects mapping files: it uses the Vendor values persisted on the selected CDRs. Multivendor remains disabled until all three selected CDRs have been mapped.

## Report options

Choose the technology according to the required session scope:

| Technology | CDR session filter |
| --- | --- |
| **NSA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `ENDC`. |
| **SA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `NR`. |

Then choose a report scope:

- **Single-vendor** generates the operator analysis without further mapping requirements.
- **Multivendor** is available only when every selected CDR already contains a Vendor mapping. It creates vendor series where applicable, while keeping O2/EE as operator comparisons. During rendering, template grouping dimensions named `Operator` become `Vendor`; legends named `Operator` become `Campaign`; and occurrences of `Operator` in slide titles, subtitles and chart titles become `Vendor`. `Operator` filters are deliberately not changed and continue to filter the source CDR Operator field.

Choose **Slides Templates** as well. The technology's default template is preselected; another stored NSA or SA template can be chosen for that run without changing the workspace default.

## Vendor calculation

For Vodafone and Three, the report derives vendor from the first and last value available in CDR `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI` and the corresponding mapping. During 3UK processing, Workspace materialises `GCID` from the same value as `Cid__ECI` (or `CId___ECI`). During VFUK processing, it materialises the 4G GCID as `eNodeB ID × 256 + Local Cell ID`; this is equivalent to `HEX2DEC(DEC2HEX(eNodeB ID, 5) & DEC2HEX(Local Cell ID, 2))` in Excel. It also materialises the existing 5G convention, `gNodeB ID × 4096 + Local Cell ID`, for inspection in the mapping preview. The report's Vodafone lookup remains based on the agreed 4G mapping formula. The agreed business formula is authoritative: matching mapped endpoints yield that vendor; Vodafone explicitly distinguishes Ericsson-related mixed cases, other mixed cases and missing endpoints; Three uses a mixed-vendor result for non-matching endpoints. O2 and EE remain represented as the operator.

## Generated presentation

Every NSA, SA, single-vendor and multivendor report uses the same `assets/ppt-templates/Template_CDR_analysis.pptx` (or the file with that name below the configured `APP_ASSETS_DIR`). It is a master/layout-only template and intentionally contains no slides. For every distinct `Slide` number in the selected Slides Templates, the renderer creates one new slide from its named layout, ordered by slide number. Rows with the same number represent separate charts on that slide and fill its image placeholders from left to right and then top to bottom. Commentary placeholders remain blank for analyst input.

An administrator can manage several named NSA and SA Slides Templates CSVs in the shared application library under `config/slides-templates/`. The single importer selects the required `NSA` or `SA` type (NSA by default); a non-default library template can also be moved to the other type from its Type selector. A template can be set as the default, duplicated, renamed, deleted or exported, then edited directly in the browser. Its visible name is its physical CSV filename without `.csv`; duplicates use `- Copy`, then `- Copy 2`, and so on. Every CDR row represents one chart image and declares its named PowerPoint `Layout`; the renderer creates the slide, populates its title and places generated charts in the layout's matching chart placeholders. Importing or selecting a new default template refreshes the tables below.

Generation runs as a persistent background job, so Reporting returns immediately and the work continues after navigating away or signing out. Generated filenames include the report type, scope and second-precision timestamp without a random suffix. The **Generated Reports Jobs** panel lists the complete persisted history with each job's ID, date, report name, selected datasets, template, slide count, type, multivendor state, creator, status and progress. New PPTX files are stored in the active workspace's `output/reports` directory; existing jobs created before this change are also resolved from the legacy `exports` directory. When ready, use **Download** for a direct streamed PPTX download, **Open** to open it in a new browser tab, or **Delete** to remove both the job record and generated file. If a report fails, its status exposes the error. If it contains no valid samples, re-check the selected technology, operator sheets and CDR inputs; the message indicates that the selected persisted rows did not match the relevant KPI and technology filter. For NSA, validate that the relevant RAT field actually contains an ENDC variant; for SA, validate the expected `NR` values.

## Slides Templates and chart contract

The renderer follows the visual grammar of the supplied template for every automated KPI slide: 100% stacked columns for success/quality splits, stacked count bars for failures, CDF lines for continuous KPIs, vertical bars for mean or median comparisons, distribution bars for FDTT rate buckets, and band/radio-quality scatter plots on the dedicated SA Vodafone analysis. Operator colours remain consistent with the template: 3UK orange, EE blue, VFUK red and O2 purple. `Campaign` (or the processed `period` fallback) is the benchmark/category dimension; a multivendor run replaces the operator series with the calculated operator-vendor series.

The technology condition below is always applied before the slide-level filters: NSA contains an ENDC spelling in `RAT`, `RAT_A` or `Sample_RAT_A`; SA contains `NR` in the same fields.

The current CSV schema is `Slide`, `Slide tittle`, `Slide Subtittle`, `Layout`, `Chart Tittle`, `CDR source`, `KPI`, `Chart type`, `Filters`, `Rows Aggregation`, `Column Aggregation`, `Legend` and `Legend Position`. For automated rows, all chart-definition fields are executable. `Slide Subtittle` is rendered in the second line of a chart slide's title placeholder in smaller blue text; `Chart Tittle` is the chart heading; `Legend` can replace generated captions in comma-separated order. `Legend Position` accepts `Top`, `Bottom`, `Left` or `Right`; top/bottom produce a horizontal legend row, while left/right use a vertical legend column. Blank values default to `Top`.

Two structural `Chart type` values build non-KPI slides:

- `Title Slide` creates the presentation cover, normally with the `Title Page` layout. `Slide tittle` and `Slide Subtittle` populate the layout's title and subtitle placeholders.
- `Transition Slide` creates a section divider, normally with `Title Only` or another suitable transition layout. It accepts a title and optional subtitle.

A structural slide occupies exactly one template row and cannot share its slide number with chart rows. Leave `Chart Tittle`, `CDR source`, `KPI`, `Filters`, `Rows Aggregation`, `Column Aggregation` and `Legend` empty. The former `Not Automated (preserve)` value is retained only for legacy conversion: imported legacy rows are migrated to `Title Slide` or `Transition Slide`, because an empty template has no source slide to preserve.

Write filters as semicolon-separated expressions such as `Call Family IN (VoLTE, MultiRAB); Direction = DL` or `Type_of_Test = Interactivity`. Supported operators are `IN (...)`, `NOT IN (...)`, `CONTAINS`, `NOT CONTAINS`, `=`, `!=`, `<`, `<=`, `>` and `>=`. Use processed CDR column names (case-insensitive matching is supported). `Call Family` and `Test Family` are persisted derived CDR columns and appear in the dataset Preview with a light-grey background: Call Family normalises session/call-mode values, while Test Family normalises test type/name values. `Threshold = 1.6` configures `Threshold Stacked Vertical Bars`, while `Buckets = 1,5,20,100` configures `Rate Bucket` for `Distribution Stacked Vertical Bars`; `Rate Bucket`, Threshold and Buckets remain chart-specific calculated/configuration values rather than stored CDR columns.

Write each aggregation hierarchy with `×`. `Rows Aggregation` defines the visible category/table-row hierarchy. `Column Aggregation` defines comparison series and table columns; if it is empty, the renderer uses one `(all)` series and does not duplicate category labels. For distribution charts the final column dimension is the stack/bucket breakdown. This interpretation is consistent across CDF, scatter, mean/median bars, stacked status/failure/distribution bars and tables. `Operator` resolves to the calculated operator-vendor comparison field in multivendor reports. The valid automated chart types are `100% Stacked Vertical Bars`, `Count Stacked Horizontal Bars`, `CDF Line`, `Scatter`, `Table`, `Average Vertical Bars`, `Median Vertical Bars`, `Distribution Stacked Vertical Bars` and `Threshold Stacked Vertical Bars`; the structural types are `Title Slide` and `Transition Slide`.

The importer accepts the current schema and compatible legacy schemas. If the headers differ, it presents a conversion confirmation: compatible names are migrated, legacy `Grouping` is split into row/column grouping, new optional presentation fields remain blank, and a missing layout is assigned from the number of CDR charts on that slide. Any remaining invalid chart contract is presented in a floating import-failure dialog.

<!-- SLIDES_TEMPLATES:START -->

Export the active NSA or SA Slides Template from Admin before editing it. The tables below always reflect the active CSV files under `config/slides-templates/default/`.

### NSA template

| Slide | Slide tittle | Slide Subtittle | Layout | Chart Tittle | CDR source | KPI | Chart type | Filters | Rows Aggregation | Column Aggregation | Legend | Legend Position |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | First | — | Title and 1 column + Comments | — | CDR-Voice | Call_Status | 100% Stacked Vertical Bars | — | Operator | Campaign | — | Top |

### SA template

| Slide | Slide tittle | Slide Subtittle | Layout | Chart Tittle | CDR source | KPI | Chart type | Filters | Rows Aggregation | Column Aggregation | Legend | Legend Position |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | First | — | Title and 1 column + Comments | — | CDR-Voice | Call_Status | 100% Stacked Vertical Bars | — | Operator | Campaign | — | Top |

<!-- SLIDES_TEMPLATES:END -->
