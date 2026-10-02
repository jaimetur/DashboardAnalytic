# Workspace Config

Workspace Config is a dedicated page for settings owned by the active workspace: Report Templates Management, Main Cities, Operator & Vendor Maps (including Spectrum Holdings) and Scoring & GAP Analysis Setup. These settings remain workspace-scoped and are included in the applicable import, export, transfer, backup and restore workflows.

> [!IMPORTANT]
> **Workspace settings.** Every edit on this page belongs to the active workspace. Application Config controls shared runtime settings.

> [!TIP]
> **Save versus export.** Save persists edits in the workspace. Export downloads a portable copy; it does not replace the Save action.

Open **Config → Workspace Config** from the main navigation at `/workspace-config`. Template, mapping and Main Cities actions use routes below `/workspace-config/`. The page uses the same teal/navy palette as Application Config and its Page Sections navigator links to the panels.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Access and active workspace | [Open section](#access-and-active-workspace) |
| Report Templates Management | [Open section](#report-templates-management) |
| Report Template Editor | [Open section](#report-template-editor) |
| Report Template reference | [Open section](#report-template-reference) |
| Operator & Vendor Maps | [Open section](#operator-vendor-maps) |
| Spectrum Holdings | [Open section](#spectrum-holdings) |
| Main Cities | [Open section](#main-cities) |
| Portable operations | [Open section](#portable-operations) |
| Scoring & GAP Analysis Setup | [Open section](#scoring-gap-analysis-setup) |

## Access and active workspace

The Workspace Config section is available to `user-editor`, `admin` and `super-admin` accounts. `user-viewer` accounts do not have access. Open a workspace before using its configuration panels; their contents and changes belong only to that workspace.

## Report Templates Management

Templates belong to the active workspace and are stored in that workspace database's `report_templates` table. Import, export, backup and transfer packages serialize them as portable CSV files, but those files are package artifacts rather than the live source of record. Obsolete `slides-templates` directories are removed by the current migration and portability flows.

Report Templates Management supports NSA and SA templates, one default for each technology, and the editor described below. Template names are unique per NR Mode, so an NSA and an SA template may share a name.

The library is sorted by NR Mode (NSA first) and then name; its columns show the NR Mode, creation and last update times, and **Last Updated by**, the user who last imported, edited, renamed, duplicated, promoted or moved the template.

Available actions:

- New
- Import CSV
- Edit
- Rename
- Duplicate
- Change NR Mode (NSA/SA)
- Set Default
- Export
- Delete

**New Template** creates a blank NSA definition and opens it for editing. Import accepts a CSV name or derives it from the filename, can convert a legacy catalogue when prompted and requires explicit overwrite confirmation for a case-insensitive name collision.

Renaming saves when you leave the name field or press Enter; the field keeps its previous name and shows an error if the save fails. Duplicate creates `- Copy`; a non-default template can move between NSA and SA when no same-name target exists.

One template can be default for each technology within a workspace. Reporting initially selects that default but does not change it when a user chooses another template for one job. A default template cannot change type or be deleted until another template becomes default. New workspaces start without templates.

The row Export action downloads that individual CSV; portable ZIP export is available under Import / Export / Transfer.

## Report Template Editor

**Edit** opens the selected template in a large dialog. The surrounding page controls are omitted from the embedded editor.

### Grid behaviour

- The table scrolls vertically and horizontally inside its viewport.
- The bottom action bar remains visible.
- Shared slide cells are visually merged across charts on the same slide.
- Row controls add, remove, reorder and preview chart definitions.
- **Re-Enumerate Slides** rewrites slide numbers into their current visual order.
- Edited cells use a light pastel-yellow background.
- Newly inserted text is highlighted more strongly.
- A successful save resets all change highlighting.
- **Find & Replace** (or Ctrl/Cmd+F inside the editor) searches every editable cell of the template. Matching cells are outlined and the current one is highlighted; Enter and Shift+Enter (or Next and Previous) move between them. **Replace** changes every occurrence in the current cell and **Replace All** changes every occurrence in the template after a confirmation. Replacements are ordinary unsaved edits until **Save Template**; **Match case** restricts matching to the exact capitalization.

### Validation

- Manual cell edits are validated after a short pause and when leaving the cell. Save revalidates the complete grid and stops if a row or filter is malformed.
- Filter errors identify `Slide: n - Chart: n`.
- Fixing the invalid cell clears the error message.
- Filter conditions render on separate lines with visual bullets; bullets are not stored in the cell.
- CSV filter cells retain one condition per line.

### Assistance and previews

- Searchable single-select assistance for layouts, chart types, fields and positions.
- Ordered multi-select assistance for Rows, Columns and Legend.
- Shared Filter Builder with parsed-expression display.
- Chart Data Preview opens the full filtered dataset directly.
- Chart Preview reuses the shared Interactive Preview.
- **Update Template** applies preview values to the in-memory row; it does not save to disk.
- **Auto-calculated Fields** opens the shared active-workspace field manager.

**Save Template** validates and persists the complete grid atomically. Dashboard comment reconciliation runs separately when slide identity changes; any required combined CDR update also runs after the save response. The Dashboard viewer refreshes the saved template when the editor closes. A combined CDR update is queued only when a template adds a source field missing from that CDR table.

Removing the last template reference leaves the existing column available for future reuse. Close, Escape and backdrop actions preserve the editor when unsaved changes still require a decision.

## Report Template reference

This is the canonical authoring reference for templates used by both [E2E Dashboards](e2e-dashboards.md) and [E2E Reporting](e2e-reporting.md). The common `assets/ppt-templates/Template_CDR_analysis.pptx` supplies the masters, named layouts and placeholders. Each distinct `Slide` value creates one slide; chart rows sharing that value fill its chart placeholders in row order.

### Template columns

| Column | Purpose |
| --- | --- |
| `Slide` | Positive slide number. Rows are sorted by this value; rows with the same number form one slide. |
| `Slide Tittle` | Shared slide title. The historical `Tittle` spelling is part of the CSV schema. |
| `Slide Subtittle` | Optional shared slide subtitle. |
| `Layout` | Exact layout name from `Template_CDR_analysis.pptx`. |
| `Chart Tittle` | Optional title drawn inside the chart. |
| `CDR source` | `CDR-Data`, `CDR-Voice` or `CDR-Speech`; leave blank for structural slides. |
| `KPI` | Processed CDR field or metric expression to render. |
| `Chart type` | Automated chart type or structural slide type. |
| `Filters` | Conditions applied before aggregation, one per line and terminated with `;`. |
| `Rows Aggregation` | Category/table-row hierarchy. Separate dimensions with `×`. |
| `Column Aggregation` | Comparison-series/table-column hierarchy. Separate dimensions with `×`. |
| `Legend` | Optional field whose plotted or filtered values should be explained. Blank means no legend. |
| `Legend Position` | `Top`, `Bottom`, `Left` or `Right`; blank defaults to `Top`. |
| `Legend Format` | Optional list defining legend colour, font, styles and relative size. Blank retains automatic formatting. |
| `Label Position` | Optional value placement: `None`, `Top`, `Up`, `Middle` or `Down`. Blank retains automatic placement. |
| `Label Format` | Optional list defining label colour, font, styles and relative size. Blank retains automatic formatting. |
| `Axis X Range` | Optional CDF limits in KPI units: `[min,max]`, `[min,]` or `[,max]`. Blank keeps the automatic domain. |
| `Axis Y Range` | Optional CDF cumulative-percentage limits from 0 to 100, using the same syntax. Blank keeps 0–100%. |
| `Exclude Null/Empty` | `Yes` removes rows whose plotted value is null or empty before chart calculations. Blank keeps them. |
| `Exclude Zero` | `Yes` removes rows whose plotted numeric value is exactly zero before chart calculations. Blank keeps them. |

For multi-chart slides, the editor visually groups `Slide`, `Slide Tittle`, `Slide Subtittle` and `Layout`; the CSV still stores them on every row.

### Structural slides

Use one row without `CDR source` or KPI fields. A structural row cannot share its slide number with chart rows.

- `Title Slide` normally uses `Title Page` and fills title/subtitle placeholders.
- `Transition Slide` normally uses `Title Only` and creates a section divider.
- Title and Transition subtitles use the template's yellow accent (theme accent 4) in exported presentations, whatever layout hosts them.
- In E2E Dashboards, a Title Slide that opens the Dashboard also lists the Scope, Regions and Cities below its subtitle and decorative line, in the viewer and in the exported PPT.

```text
Slide: 1
Slide Tittle: NetCheck 5G Executive Dashboard
Slide Subtittle: 2026-Q2 · Operator Comparison
Layout: Title Page
Chart type: Title Slide
```

```text
Slide: 6
Slide Tittle: Voice service analysis
Layout: Title Only
Chart type: Transition Slide
```

### Supported chart types

Automated rows support:

- `100% Stacked Vertical Bars`
- `Count Stacked Horizontal Bars`
- `CDF Line`
- `Multi KPI CDF Lines`
- `Scatter`
- `Map`
- `Table`
- `Average Vertical Bars`
- `Median Vertical Bars`
- `Distribution Stacked Vertical Bars`
- `Threshold Stacked Vertical Bars`

Choose a KPI and at least one Rows or Column Aggregation dimension. `CDF Line` creates one curve per complete aggregation combination. Count charts retain empty combinations where required so comparisons remain aligned.

Axis ranges are visual settings, not data filters, and are available to every chart family with a numeric axis. For example, `Axis X Range: [0.01,]` starts the horizontal axis at `0.01` while retaining its automatically calculated maximum; `[,30]` retains the automatic minimum and fixes the maximum at `30`. Empty range cells preserve the existing automatic behaviour.

Percentage axes continue to use values from 0 to 100, while count, KPI, coordinate and scatter axes use their native units. Category axes and tables have no numeric domain to constrain.

`Label` is available to every chart family. For bars, `None` hides values, `Top` places them outside the bar, and `Up`, `Middle` and `Down` place them inside near the leading edge, centre or origin edge; horizontal bars map those directions to outside-right, inside-right, centre and inside-left.

For CDF, scatter and map charts the same setting places point or endpoint labels around the plotted mark. An empty cell preserves each renderer's existing automatic behaviour.

`Exclude Null/Empty` and `Exclude Zero` are independent and apply to every chart family. For scatter charts the exclusions are checked on both plotted axes; for CDF and Multi KPI CDF charts they are checked on each plotted metric before the cumulative distribution is calculated.

This allows a CDF to begin at its first non-zero observation instead of merely hiding the zero-valued section with an axis range.

### Chart recipes

The examples show chart-specific cells. Add the shared `Slide`, titles and `Layout` appropriate to the target layout.

#### 100% Stacked Vertical Bars

Use for proportions, success ratios and categorical quality splits. KPI categories become stack segments.

```text
CDR source: CDR-Voice
KPI: Call_Status
Chart type: 100% Stacked Vertical Bars
Filters: Call Family IN (VoLTE, MultiRAB); Operator IN (Vodafone, 3, EE)
Rows Aggregation: Call Family
Column Aggregation: Operator × Campaign
Legend Position: Right
```

#### Count Stacked Horizontal Bars

Use for event or failure counts. Rows form horizontal categories and the KPI normally supplies statuses or causes.
Column hierarchy headers keep complete aggregation values in both the Dashboard canvas and exported PowerPoint chart. Each successive level uses a smaller font, which can shrink further to fit narrow columns; the final header row has its own space above the data.

```text
CDR source: CDR-Data
KPI: Test_Result
Chart type: Count Stacked Horizontal Bars
Filters: Test Family IN (FDFS, FDTT); Test_Result IN (Failed, Dropped)
Rows Aggregation: Test Family × City
Column Aggregation: Operator × Campaign
Legend Position: Bottom
```

#### CDF Line

Use for continuous metrics such as throughput, duration, latency or MOS.

```text
CDR source: CDR-Data
KPI: Mean_Data_Rate
Chart type: CDF Line
Filters: Test_Result = Completed; Test_Name CONTAINS FDFS; Direction = DL
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Bottom
```

With two operators and two campaigns this produces four curves. With multiple campaigns, the latest campaign is emphasised within each comparison family.

#### Multi KPI CDF Lines

Separate continuous KPI names with `|`. The renderer keeps the shared filters, aggregations and legend and places one CDF panel per measure.

```text
CDR source: CDR-Data
KPI: NR_PCell_SINR_Avg | LTE_PCell_SINR_Avg
Chart type: Multi KPI CDF Lines
Filters: Test_Result = Completed; Test_Name = FDTT http DL MT
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Right
```

#### Average Vertical Bars and Median Vertical Bars

Use Average for mean values or Median when outliers should have less influence.

```text
CDR source: CDR-Speech
KPI: LQ
Chart type: Average Vertical Bars
Filters: Call_Status = Completed; Call Family = WhatsApp
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Top
```

Change only `Chart type` to `Median Vertical Bars` for the median.

#### Distribution Stacked Vertical Bars

Use explicit numeric ranges with `Buckets = ...`, or ordered upper bounds with `Buckets < ...` / `Buckets <= ...`. Upper-bound mode generates `belowN` categories plus `Above`; use `Rate Bucket` as the final column aggregation.

```text
CDR source: CDR-Data
KPI: Mean_Data_Rate
Chart type: Distribution Stacked Vertical Bars
Filters: Test_Result = Completed; Test_Name = FDTT http DL MT; Buckets < 2,5,20,100
Rows Aggregation: Operator
Column Aggregation: Campaign × Rate Bucket
Legend Position: Right
```

With upper-bound mode, `Buckets < 2,5,20,100` evaluates each value against the limits in order and produces `below2`, `below5`, `below20`, `below100` or `Above`. Use `Buckets < 1,3,10,20` for the corresponding FDTT UDP UL distribution. `<=` is also accepted when boundary values must remain inside their named bucket.

Explicit ranges such as `Buckets = 1,5,20` produce `<1`, `1-5`, `5-20` and `20+`. Negative limits use `to`, so `Buckets = -110,-100,-90,-80` produces `< -110`, `-110 to -100`, `-100 to -90`, `-90 to -80` and `-80+` for RSRP. Stacked segments and legend entries always follow ascending numeric order, regardless of the order in which values appear in the CDR rows.

#### Threshold Stacked Vertical Bars

Use for a below/above distribution around one threshold.

```text
CDR source: CDR-Speech
KPI: LQ
Chart type: Threshold Stacked Vertical Bars
Filters: Call_Status = Completed; Call Family = VoLTE; Threshold = 1.6
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Right
```

The legend shows the configured threshold, for example `< 1.6` and `≥ 1.6`; `Threshold = -110` produces `< -110` and `≥ -110`.

#### Scatter

Use `Metric vs Dimension` to compare a KPI with a radio or quality dimension.

```text
CDR source: CDR-Speech
KPI: LQ vs Playing_RSRP_NR_Avg
Chart type: Scatter
Filters: Call_Status = Completed; Call Family = WhatsApp
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Bottom
```

#### Map

Use latitude and longitude in `Latitude vs Longitude` order. Aggregations and legend determine point grouping and colour.

```text
CDR source: CDR-Data
KPI: Test_Start_Latitude vs Test_Start_Longitude
Chart type: Map
Filters: G_Level_4 = London
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend: Test_Result
Legend Position: Right
```

#### Table

Use when exact values are more useful than a chart. Rows and columns form the axes; KPI supplies the aggregated cell value.

```text
CDR source: CDR-Voice
KPI: Call_Setup_Time
Chart type: Table
Filters: Call_Status = Completed
Rows Aggregation: City
Column Aggregation: Operator × Campaign
Legend Position: Top
```

### Template filter language

Conditions are joined with logical AND and separated by `;`. Column matching is case-insensitive.

```text
Call Family IN (VoLTE, MultiRAB); Direction = DL; vendor NOT CONTAINS (Mixed, Other)
```

| Operator | Example |
| --- | --- |
| Equals / not equal | `Call_Status = Completed`, `Operator != EE` |
| List inclusion / exclusion | `Operator IN (VF, O2, 3, EE)`, `Campaign NOT IN (2025-Q4)` |
| Contains / not contains | `Test_Name CONTAINS FDFS`, `vendor NOT CONTAINS (Mixed, Other)` |
| Numeric comparison | `LQ < 1.6`, `Mean_Data_Rate >= 20` |

`IN`, `NOT IN`, `CONTAINS` and `NOT CONTAINS` accept comma-separated values. Parentheses are optional in Filter Builder input. A comma separates values within one condition; use `;` between independent conditions. `Threshold = 1.6` configures threshold charts and `Buckets = 1,5,20,100` configures distribution ranges.

### Aggregations and legends

Selection order defines the hierarchy:

```text
Rows Aggregation: Call Family × G Level 4
Column Aggregation: Operator × Campaign
```

- Rows supplies chart categories or table rows.
- Column supplies comparison series or table columns.
- Blank Column Aggregation creates one `(all)` comparison.
- `Campaign` is ordered chronologically from oldest to newest.
- In Multivendor scope, `Operator` aggregation resolves to the mapped comparison field; an Operator filter still applies to the physical CDR Operator field.

Legend behaviour:

- Blank draws no legend.
- A KPI or aggregation dimension shows plotted values.
- A field used only by Filters shows its applied values as contextual text.
- CDF handles reproduce series colour and relative line width.
- Threshold legends show below/above colours and the configured value.
- Bucket legends show readable ranges derived from `Buckets`.

Top/Bottom produces a compact horizontal legend; Left/Right produces a vertical legend and reserves plot space.

### Multi-chart slides, operators and colours

Rows sharing a `Slide` number create separate charts on one slide. They must share `Slide Tittle`, `Slide Subtittle` and `Layout`, may use different sources, KPIs, filters and chart types, and require at least as many placeholders as chart rows.

Operator and Vendor aliases resolve to the canonical values configured in Workspace Config without changing the source workbook. Their table order controls Operator, Subscriber, Vendor and combined Operator_Vendor chart dimensions. Each canonical row defines its chart theme colour; multiple campaigns or operators using one identity receive contrasting shades derived from that colour.

## Operator & Vendor Maps

The Operator & Vendor Maps panel contains Operator Maps, Vendor Maps and Spectrum Holdings as independently collapsible subpanels. Their light blue headers distinguish them from the dark parent header. Existing mapping controls and saved expansion states remain available inside each subpanel.

### Operator Maps

The table groups raw Operator labels under one canonical identity for charts. Each row shows **Order**, **Colour**, **Canonical label**, **Mapped source labels** and **Actions**. Enter source aliases one per line; comma and semicolon separators are accepted too. The canonical label also maps to itself automatically, so it need not be repeated among the aliases. An alias cannot belong to two canonical groups.

Use **Add canonical mapping** to create a group. Change its label, aliases or colour and press **Save** to update it. **Move up** and **Move down** set its position in Operator charts and in Subscriber dimensions; the first and last rows cannot move beyond the table. **Delete** removes the entire group, including its aliases, after confirmation.

Canonical renames update exact matching references in Report Templates and saved Dashboards.

The colour picker sets the group's chart theme colour; charts can derive related shades to distinguish campaigns or series. Order and colour are presentation choices, while aliases make source labels such as `Vodafone UK` resolve to the intended canonical Operator. These settings affect chart grouping, legends and template filters.

They do not rewrite source workbooks, stored CDR rows or combined CDR tables. Saving, moving or deleting a group clears chart caches so later views use the new settings.

### Vendor Maps

The Vendor table has the same **Order**, **Colour**, **Canonical label**, **Mapped source labels** and **Actions** controls. Use **Add canonical mapping**, **Save**, **Move up**, **Move down** or confirmed **Delete** to manage a Vendor and all its aliases. Alias matching is case-insensitive, the canonical label maps to itself, and an alias cannot belong to two Vendor groups.

Renaming a canonical Vendor updates exact matching Report Template and saved Dashboard references.

Vendor order determines the chart sequence for Vendor dimensions and the Vendor portion of combined `Operator_Vendor` categories. The selected colour gives a Vendor a consistent chart identity, with related shades where multiple series need distinction. Aliases reconcile different source spellings for chart display and filters; they do not alter materialized CDR values. Group changes refresh chart caches without rematerializing source data.

### Spectrum Holdings

Spectrum Holdings list the licensed spectrum of each Operator for the **Spectrum** panel of [Network Insights](network-insights.md#spectrum). Enter one band per row with the header `Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes`:

```text
Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes
Vodafone,B20,FDD,Low,20,2x10 MHz
Vodafone,n78,TDD,High (TDD),90,
```

- **Operator** should match a canonical label of the Operator Maps.
- **Band** uses LTE (`B20`) or NR (`n78`) names.
- **Duplex** is `FDD`, `TDD` or `SDL`; **Band Class** is `Low`, `Mid` or `High (TDD)`. Both are inferred for known bands when left empty.
- **Bandwidth MHz** is the total bandwidth held, for example `20` for 2×10 MHz FDD.

Comma, semicolon and tab separators are accepted, so rows can be pasted from a spreadsheet. **Save Spectrum Holdings** validates every row and replaces all holdings of the workspace; an empty text area removes them. The table above the editor shows the MHz per Operator and band class.

## Main Cities

The Main Cities panel appears before Operator & Vendor Maps and lists cities found in ready CDR datasets for the active workspace. Use the center buttons to move selected or all cities between the available list and the selected list, then choose **Save Main Cities**. The setting belongs to this workspace.

Dashboard's Default Filters City multiselect and the PowerPoint export City selector provide a **Main Cities** preset. Applying it selects the configured cities that are available in the current Dashboard or export dataset selection.

## Portable operations

Administrators use Admin's existing **Import / Export / Transfer** and **Backup Protection** controls to move or restore workspace settings. Main Cities is a portable component alongside Report Templates and Operator & Vendor Maps; full-workspace packages and database backups also retain the setting. Spectrum Holdings travel inside the Operator & Vendor Maps package (format version 3); importing an older package leaves the destination's Spectrum Holdings unchanged.

For global runtime settings, see [Application Config](app-config.md). Admin's [Database Viewer](administrator-config.md#database-viewer) documents the underlying Operator and Vendor mapping tables.

## Scoring & GAP Analysis Setup

A methodology defines the complete scoring setup: its title, environments, KPI definitions and weights, aggregation hierarchy and KPI priorities. Select or create a methodology before editing its settings.

### Methodology controls

| Action | Result |
| --- | --- |
| Create / Duplicate Methodology | Start a new definition or use an existing methodology as the basis for a revision. |
| Rename / edit title | Change the methodology identity or descriptive title. |
| Set Default | Choose the saved methodology initially offered for future scoring jobs. |
| Save Methodology | Validate and persist the complete methodology, including all three subpanels. |
| Export Methodology (JSON) | Download the selected methodology only. |
| Import Methodology (JSON) | Import a portable methodology document. |
| Admin Export / Backup | Package every saved methodology and the default selection together. |

> [!IMPORTANT]
> **One save operation.** Save Methodology appears above the subpanels and inside each one for convenience. Every instance saves the same complete setup; there are no independent hierarchy or priority saves.

The database is the source of record. Invalid edits do not replace the saved configuration. Historical jobs keep their methodology snapshot; changing the saved methodology changes the identity of subsequent calculations.

### Methodology Environments

Choose the environment to edit, or create, rename or delete one. Keep at least one environment with a positive overall allocation.

| Setting | What it controls |
| --- | --- |
| CDR filters: G_Level_1 and optional G_Level_2 | Which source rows belong to the environment. Leave the optional second value empty to include all its values. Overlapping environment selections are rejected. |
| Environment total | The maximum points allocated to that environment. |
| Edit weights by Points | Edit absolute KPI allocations. |
| Edit weights by Weight (%) | Edit relative shares while preserving the environment total and redistributing the other shares proportionally. |
| Distribute points keeping percentages | Allocate a new total using a reference environment's relative KPI shares. Thresholds and formulas are not copied. |

Creating an environment copies KPI rules and proportions from the selected reference; its own CDR filters determine the rows included. NetCheck 2026 includes Walk with zero initial points and editable relative weights.

### KPI Definitions, Scoring & Thresholds

Expand this subpanel to edit KPI specifications, thresholds and weights for the selected environment. Its pastel-red presentation separates the detailed KPI editor from the green setup panels.

- Edit the category, label, source CDR type, direction and mapping curve: Linear, Quadratic or Smooth curve.
- Use the KPI Definition pencil to edit the formula and filter JSON in a larger dialog. Closing the dialog retains the draft until Save Methodology.
- Configure thresholds, KPI type and score interpolation anchors. Ultra can be absent, numeric or derived from the best valid KPI measurement in its comparison context.
- Add or delete KPIs; at least one must remain. New KPIs receive stable K-number identifiers. Moving or deleting rows does not renumber other KPIs.
- Move KPIs within their category, change their category or reorder whole categories. Category totals show points, environment-relative weights and global weights.
- Renaming a KPI code updates its saved GAP priority reference without changing its priority.

Max Points displays two decimal places while retaining full precision for calculation and unchanged allocations when saved. The formula determines the calculation basis; formulas and filters must use supported engine fields and operations.

### Methodology Aggregation Hierarchy

Reorder Operator, Vendor, Region, City and Campaign. Operator is mandatory for calculations. The hierarchy controls the selection panels and hierarchical result tables, charts and PowerPoint output.

### Methodology KPIs Priorities for GAP analysis

Maintain the transferable KPI priority list with up/down, first/last or specific-position controls. The position must be a whole number from 1 to the number of KPIs; Enter applies it and Escape cancels.

> [!NOTE]
> **Priority and result ordering.** The saved priority list does not currently determine GAP result order. Individual comparisons sort signed GAP from lowest to highest, with unavailable values last; All Operators retains KPI definition order.

Web and PowerPoint GAP tables include a final sum for each comparison column. Individual PPT comparisons show Average KPI GAP and the average of the column GAP totals. These are distinct statistics; see the [complete Scoring & GAP Analysis guide](scoring-gap-analysis.md) for examples, coverage rules and JSON formats.
