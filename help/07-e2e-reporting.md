# E2E Reporting

Use **E2E Reporting → NetCheck CDR Reports** to create a PowerPoint report or a persistent set of PNG charts from processed CDR-Data, CDR-Voice and CDR-Speech datasets.

## Before generating a report

Process at least one ready CDR of each type in Workspace. The reporting page can combine several datasets of the same type, retaining their `Campaign` values for multi-campaign comparisons.

Choose the required technology:

| Technology | Included sessions |
| --- | --- |
| NSA | Values containing `ENDC` in `RAT`, `RAT_A` or `Sample_RAT_A` |
| SA | Values containing `NR` in the same fields |

Choose the scope:

- **Operator Comparison** uses the normalised operator dimension.
- **Multivendor Comparison** requires every selected CDR to have a persisted Vendor mapping.
- In Multivendor Comparison, `Operator` aggregations resolve to the operator-vendor comparison field.
- `Operator` filters still apply to the physical CDR Operator column.

Default dataset selection:

- Operator Comparison selects the two newest CDRs of each type, or the only available CDR.
- Changing to Vendor Comparison reduces multiple selections to the newest currently selected CDR of each type.
- An existing single selection is preserved even when it is not the newest dataset in the workspace.

## Slides Templates

PowerPoint reports use CSV Slides Templates managed in **Admin → Slides Templates Management**. Administrators can create, duplicate, import, rename, export and classify NSA/SA templates there.

The common `assets/ppt-templates/Template_CDR_analysis.pptx` supplies masters and layouts:

- Each distinct `Slide` value creates one slide.
- `Layout` chooses the named PowerPoint layout.
- Chart rows sharing a slide fill chart placeholders in row order.
- Commentary placeholders remain blank for the analyst.

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
| `Filters` | Conditions applied before aggregation, stored one per line and terminated with `;`. |
| `Rows Aggregation` | Category/table-row hierarchy. Separate dimensions with `×`. |
| `Column Aggregation` | Comparison-series/table-column hierarchy. Separate dimensions with `×`. |
| `Legend` | Optional field whose chart values or applied filter values should be explained. Blank means no legend. |
| `Legend Position` | `Top`, `Bottom`, `Left` or `Right`; blank defaults to `Top`. |

For multi-chart slides, the editor visually groups `Slide`, `Slide Tittle`, `Slide Subtittle` and `Layout`. The CSV still stores those values on every row. Assistance includes the Filter Builder, field suggestions and chart-data/chart-image previews.

### Structural slides

Use one row with no `CDR source` or KPI fields:

- `Title Slide` normally uses `Title Page` and fills the title/subtitle placeholders.
- `Transition Slide` normally uses `Title Only` and creates a section divider.

A structural slide cannot share its slide number with chart rows.

Example cover row (only the relevant values are shown):

```text
Slide: 1
Slide Tittle: NetCheck 5G Executive Report
Slide Subtittle: 2026-Q2 · Operator Comparison
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
| List inclusion / exclusion | `Operator IN (VF, O2, 3, EE)`, `Campaign NOT IN (2025-Q4)` |
| Contains / not contains | `Test_Name CONTAINS FDFS`, `vendor NOT CONTAINS (Mixed, Other)` |
| Numeric comparison | `LQ < 1.6`, `Mean_Data_Rate >= 20` |

`IN`, `NOT IN`, `CONTAINS` and `NOT CONTAINS` accept comma-separated values. Parentheses are optional in Filter Builder input; the shared parser adds them to the generated expression.

More filter examples:

```text
Operator = Vodafone
Campaign IN (2026-Q1, 2026-Q2)
vendor NOT CONTAINS (Mixed, Other)
Test_Name CONTAINS FDFS
LQ >= 1.6; LQ < 4.0
```

Use `;` rather than a comma to join independent conditions. A comma only separates values belonging to the same `IN`, `NOT IN`, `CONTAINS` or `NOT CONTAINS` condition.

`Call Family` and `Test Family` are materialised derived fields and use a light-grey background in CDR Preview.

- `Threshold = 1.6` configures threshold charts.
- `Buckets = 1,5,20,100` configures distribution-chart ranges.

## Aggregations and legends

Use `×` to define a hierarchy, for example:

```text
Rows Aggregation: Call Family × G Level 4
Column Aggregation: Operator × Campaign
```

- Rows Aggregation supplies categories or table rows.
- Column Aggregation supplies comparison series or table columns.
- Blank Column Aggregation produces one `(all)` comparison.
- `Campaign` compares selected CDRs and is ordered oldest to newest.
- In multivendor reports, `Operator` aggregation resolves to the mapped comparison field.

Legend behaviour:

- Blank means no legend.
- A KPI or aggregation dimension produces entries from plotted values.
- A field used only by Filters displays its applied values as contextual text.

Special chart legends include:

- CDF Lines reproduce series colour and relative line width.
- Threshold charts show below/above-threshold colours and the configured threshold value.
- Bucket legends show readable ranges derived from `Buckets`.

Use `Top` or `Bottom` for a compact horizontal legend and `Left` or `Right` for a vertical legend. Side placement reserves plot space to prevent overlap.

### Multi-chart slides

Rows with the same `Slide` number create separate charts on one PowerPoint slide.

- They must share `Slide Tittle`, `Slide Subtittle` and `Layout`.
- They may use different sources, KPIs, filters and chart types.
- The layout needs at least as many chart placeholders as chart rows.

Example: place a CDF Line and Average Vertical Bars on Slide 8 to compare a throughput distribution with its headline average.

## Operators, vendors and colours

Recognised historical aliases resolve to `VF`, `O2`, `3` or `EE` for reporting. This does not alter the source workbook.

Vendor colour families are stable:

- Ericsson: green.
- Huawei: red.
- Samsung: yellow.
- NSN: blue.
- Multiple operators using one vendor receive distinct shades.

## Output and jobs

**Generate PowerPoint Report** queues a report job. Its PPTX is stored in `output/reports/<report-name>/`; rendered PNG charts are stored in `output/reports/<report-name>/report-charts/`.

**Generate Report Charts** queues a Chart Set job under `output/charts/<timestamp>/`.

The Charts Panel supports:

- report-generated and standalone sets;
- enlarged Interactive Preview;
- filtered-data inspection;
- ZIP downloads and cleanup;
- source-template editing for administrators.

Reports and Chart Sets appear together in **Reports and Charts Jobs** and share the workspace `generated_jobs` table. The UI preserves the appropriate actions for each type.

If a job fails, consult **App Logs** and retry it after correcting the reported input or template issue. Completed jobs can be relaunched in the same row; relaunch removes their previous output first.
