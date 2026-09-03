# 5. E2E PowerPoint Reporting

Use **E2E Reporting → NetCheck CDR Reports** to create a PowerPoint report or a persistent set of PNG charts from processed CDR-Data, CDR-Voice and CDR-Speech datasets.

## Before generating a report

Process at least one ready CDR of each type in Workspace. The reporting page can combine several datasets of the same type, retaining their `Campaign` values for multi-campaign comparisons.

Choose the required technology:

| Technology | Included sessions |
| --- | --- |
| NSA | Values containing `ENDC` in `RAT`, `RAT_A` or `Sample_RAT_A` |
| SA | Values containing `NR` in the same fields |

Choose **Operator Comparison** for normal operator analysis, or **Multivendor Comparison** when every selected CDR has a persisted Vendor mapping. In a multivendor report, grouping dimensions named `Operator` are resolved as the operator-vendor comparison field; `Operator` filters still apply to the physical CDR Operator column.

The reporting page warns when multivendor and multiple campaigns are selected together. It preselects the most recent CDR of each type, but you can retain any valid selection.

## Slides Templates

PowerPoint reports are built from Slides Templates managed in **Admin → Slides Templates Management**. They are CSV definitions, not a fixed embedded report. Create, duplicate, import, rename, export and select NSA or SA templates there, then open one in **Slides Templates Editor**.

The common PowerPoint file in `assets/ppt-templates/Template_CDR_analysis.pptx` supplies slide masters and layouts. For each distinct `Slide` value, the renderer creates a slide from the declared `Layout`; chart rows sharing a slide number fill the available chart placeholders in order. Commentary placeholders are left blank for the analyst.

Templates are stored under `config/slides-templates/`. The documentation is static: saving a template never rewrites this file or publishes a current template definition into it.

## Template columns

| Column | Purpose |
| --- | --- |
| `Slide` | Positive slide number. Rows are sorted by this value when saved. Rows with the same number form one slide. |
| `Slide Tittle` | Shared slide title. The spelling `Tittle` is intentional and is part of the CSV schema. |
| `Slide Subtittle` | Optional shared slide subtitle. |
| `Layout` | Exact layout name from `Template_CDR_analysis.pptx`. |
| `Chart Tittle` | Optional title drawn inside the chart. |
| `CDR source` | `CDR-Data`, `CDR-Voice` or `CDR-Speech`. Leave empty for structural slides. |
| `KPI` | Processed CDR field to render. |
| `Chart type` | Automated chart type or a structural slide type. |
| `Filters` | Semicolon-separated conditions applied before aggregation. |
| `Rows Aggregation` | Category/table-row hierarchy. Separate dimensions with `×`. |
| `Column Aggregation` | Comparison-series/table-column hierarchy. Separate dimensions with `×`. |
| `Legend` | Optional comma-separated legend labels or fields. |
| `Legend Position` | `Top`, `Bottom`, `Left` or `Right`; blank defaults to `Top`. |

The editor groups `Slide`, `Slide Tittle`, `Slide Subtittle` and `Layout` visually for multi-chart slides, but the CSV still stores those values on every row. It also provides a Filter Builder, contextual column suggestions and chart-data/chart-image previews.

### Structural slides

Use one row with no `CDR source` or KPI fields:

- `Title Slide` normally uses `Title Page` and fills the title/subtitle placeholders.
- `Transition Slide` normally uses `Title Only` and creates a section divider.

A structural slide cannot share its slide number with chart rows.

Example cover row (only the relevant values are shown):

```text
Slide: 1
Slide Tittle: NetCheck 5G Executive Report
Slide Subtittle: 2026 Q2 · Operator Comparison
Layout: Title Page
Chart type: Title Slide
```

Example divider row:

```text
Slide: 6
Slide Tittle: Voice service analysis
Layout: Title Only
Chart type: Transition Slide
```

## Supported chart types

Automated rows support:

- `100% Stacked Vertical Bars`
- `Count Stacked Horizontal Bars`
- `CDF Line`
- `Scatter`
- `Table`
- `Average Vertical Bars`
- `Median Vertical Bars`
- `Distribution Stacked Vertical Bars`
- `Threshold Stacked Vertical Bars`

Choose a KPI and at least one Rows or Column Aggregation dimension for every automated row. `CDF Line` creates one curve per complete aggregation combination. Count charts retain empty combinations so comparisons remain aligned.

### Chart recipes

The examples below show the chart-specific fields. Add the shared `Slide`, titles and `Layout` fields appropriate for the target PowerPoint layout.

#### 100% Stacked Vertical Bars

Use for proportions, success ratios and categorical quality splits. The KPI is the field whose categories become the stack segments.

```text
CDR source: CDR-Voice
KPI: Call_Status
Chart type: 100% Stacked Vertical Bars
Filters: Call Family IN (VoLTE, MultiRAB); Operator IN (Vodafone, 3, EE)
Rows Aggregation: Call Family
Column Aggregation: Operator × Campaign
Legend Position: Right
```

This produces one 100% bar per operator/campaign comparison, split by `Call_Status`.

#### Count Stacked Horizontal Bars

Use for counts of failures or events. Rows form the horizontal categories and the KPI normally supplies the stacked statuses or failure causes.

```text
CDR source: CDR-Data
KPI: Test_Result
Chart type: Count Stacked Horizontal Bars
Filters: Test Family IN (FDFS, FDTT); Test_Result IN (Failed, Dropped)
Rows Aggregation: Test Family × City
Column Aggregation: Operator × Campaign
Legend Position: Bottom
```

All combinations of the selected aggregation values are retained, including zero-count combinations, so operator/campaign comparisons remain aligned.

#### CDF Line

Use for continuous metrics such as throughput, duration, latency or MOS. Every complete Rows/Columns Aggregation combination creates one line.

```text
CDR source: CDR-Data
KPI: Mean_Data_Rate
Chart type: CDF Line
Filters: Test_Result = Completed; Test_Name CONTAINS FDFS; Direction = DL
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Bottom
```

With two operators and two campaigns, the example produces four CDF lines. A single campaign is emphasised; with multiple campaigns the latest campaign is emphasised within each comparison family.

#### Average Vertical Bars and Median Vertical Bars

Use for one numeric summary per aggregation combination. Choose `Average Vertical Bars` for mean values or `Median Vertical Bars` where outliers should have less influence.

```text
CDR source: CDR-Speech
KPI: LQ
Chart type: Average Vertical Bars
Filters: Call_Status = Completed; Call Family = WhatsApp
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Top
```

To show the median instead, change only `Chart type` to `Median Vertical Bars`.

#### Distribution Stacked Vertical Bars

Use to show how a numeric KPI is distributed across explicit ranges. Add `Buckets` in Filters and use `Rate Bucket` as the final column aggregation dimension.

```text
CDR source: CDR-Data
KPI: Mean_Data_Rate
Chart type: Distribution Stacked Vertical Bars
Filters: Test_Result = Completed; Test_Name CONTAINS FDTT; Buckets = 1,5,20,100
Rows Aggregation: Operator
Column Aggregation: Campaign × Rate Bucket
Legend Position: Right
```

The bucket values define the boundaries; adjust them to the KPI unit and the business thresholds being analysed.

#### Threshold Stacked Vertical Bars

Use for a pass/fail distribution around one threshold. Add `Threshold` in Filters.

```text
CDR source: CDR-Speech
KPI: LQ
Chart type: Threshold Stacked Vertical Bars
Filters: Call_Status = Completed; Call Family = VoLTE; Threshold = 1.6
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Right
```

#### Scatter

Use for the relationship between a KPI and a radio/quality dimension. The KPI can use the `Metric vs Dimension` form where supported by the processed CDR columns.

```text
CDR source: CDR-Speech
KPI: LQ vs Playing_RSRP_NR_Avg
Chart type: Scatter
Filters: Call_Status = Completed; Call Family = WhatsApp
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Bottom
```

#### Table

Use when exact values are more useful than a chart. Rows and columns form the table axes; KPI supplies the aggregated cell value.

```text
CDR source: CDR-Voice
KPI: Call_Setup_Time
Chart type: Table
Filters: Call_Status = Completed
Rows Aggregation: City
Column Aggregation: Operator × Campaign
Legend Position: Top
```

## Filters

Write one or more conditions separated by `;` (logical AND). Column names are matched case-insensitively against the selected processed CDR source.

```text
Call Family IN (VoLTE, MultiRAB); Direction = DL; vendor NOT CONTAINS (Mixed, Other)
```

Supported operators are:

| Operator | Example |
| --- | --- |
| Equals / not equal | `Call_Status = Completed`, `Operator != EE` |
| List inclusion / exclusion | `Operator IN (Vodafone, O2, 3, EE)`, `Campaign NOT IN (2025 Q4)` |
| Contains / not contains | `Test_Name CONTAINS FDFS`, `vendor NOT CONTAINS (Mixed, Other)` |
| Numeric comparison | `LQ < 1.6`, `Mean_Data_Rate >= 20` |

`IN`, `NOT IN`, `CONTAINS` and `NOT CONTAINS` accept comma-separated values enclosed in parentheses. The Filter Builder creates the same syntax.

More filter examples:

```text
Operator = Vodafone
Campaign IN (2026 Q1, 2026 Q2)
vendor NOT CONTAINS (Mixed, Other)
Test_Name CONTAINS FDFS
LQ >= 1.6; LQ < 4.0
```

Use `;` rather than a comma to join independent conditions. A comma only separates values belonging to the same `IN`, `NOT IN`, `CONTAINS` or `NOT CONTAINS` condition.

`Call Family` and `Test Family` are materialised derived fields. They appear in CDR Preview with a light-grey background so they can be distinguished from columns that came directly from the source CDR. `Threshold = 1.6` configures threshold charts; `Buckets = 1,5,20,100` configures rate buckets for distribution charts.

## Aggregations and legends

Use `×` to define a hierarchy, for example:

```text
Rows Aggregation: Call Family × G Level 4
Column Aggregation: Operator × Campaign
```

Rows Aggregation supplies categories (or table rows); Column Aggregation supplies comparison series (or table columns). A blank Column Aggregation produces one `(all)` comparison. `Campaign` is commonly used to compare selected CDRs. In multivendor reports, `Operator` aggregation resolves to the mapped comparison field.

Use `Legend` only when you need explicit display labels; otherwise the renderer derives captions from the aggregation values. Position the legend with `Legend Position`.

For example, enter `2026 Q2, 2026 Q1` in `Legend` to supply two explicit captions for a two-series chart. Leave it blank when the aggregation values are already the desired labels. Use `Top` or `Bottom` for a horizontal legend; use `Left` or `Right` when a vertical legend leaves more room for the plot.

### Multi-chart slides

Rows with the same `Slide` number are separate charts on one PowerPoint slide. They must use the same `Slide Tittle`, `Slide Subtittle` and `Layout`, but may use different CDR sources, KPIs, filters and chart types. Choose a layout with enough chart placeholders for the number of rows in that slide. For example, put a CDF Line and an Average Vertical Bars row on Slide 8 to compare a throughput distribution with its headline average.

## Operators, vendors and colours

Recognised historical operator aliases are normalised in the report only: Vodafone variants become `Vodafone`, Three variants become `3`, O2 variants become `O2`, and EE variants become `EE`. This does not alter the stored CDR.

For chart dimensions that use Vendor, vendor families use consistent colours: Ericsson green, Huawei red, Samsung yellow and NSN blue, with distinct shades where several operators share the vendor. Other vendors use clearly distinct neutral colours.

## Output and jobs

**Generate PowerPoint Report** queues a report job. Its PPTX is stored in `output/reports/<report-name>/`; rendered PNG charts are stored in `output/reports/<report-name>/report-charts/`.

**Generate Report Charts** queues an independent Charts Job and stores its set under `output/charts/<timestamp>/`. The Charts Panel lists standalone and report-generated sets, supports enlarged previews, downloads and cleanup. Reports Jobs and Charts Jobs retain their own status, progress and actions.

If a job fails, consult **App Logs** and retry it from its job panel after correcting the reported input or template issue.
