# Workspace Config

Workspace Config is a dedicated page for settings owned by the active workspace: Report Templates Management, Main Cities, Mappings & Reference Data (Operator, Vendor and Campaign Maps, Map Areas and Spectrum Holdings) and Scoring & GAP Analysis Setup. These settings remain workspace-scoped and are included in the applicable import, export, transfer, backup and restore workflows.

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
| Mappings & Reference Data | [Open section](#mappings-reference-data) |
| Campaign Maps | [Open section](#campaign-maps) |
| Unassigned values warning | [Open section](#unassigned-values-warning) |
| Map Areas | [Open section](#map-areas) |
| Spectrum Holdings | [Open section](#spectrum-holdings) |
| CDR type | [Open section](#cdr-type) |
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

This is the canonical authoring reference for templates used by both [E2E Dashboards](e2e-dashboards.md) and [Reporting (old)](reporting-old.md). The common `assets/ppt-templates/Template_CDR_analysis.pptx` supplies the masters, named layouts and placeholders. Each distinct `Slide` value creates one slide; chart rows sharing that value fill its chart placeholders in row order.

### Template columns

| Column | Purpose |
| --- | --- |
| `Slide` | Positive slide number. Rows are sorted by this value; rows with the same number form one slide. |
| `Slide Tittle` | Shared slide title. The historical `Tittle` spelling is part of the CSV schema. |
| `Slide Subtittle` | Optional shared slide subtitle. |
| `Layout` | Select `Title Page`, `Title Only`, or a grid named `Title + N rows + M columns`, optionally followed by `+ comments down` or `+ comments right`. Dynamic grids also appear in the selector. |
| `Chart Tittle` | Optional title drawn inside the chart. |
| `Source Dataset` | `CDR-Data`, `CDR-Voice`, `CDR-Speech` or `CDR-All`; leave blank for structural slides. `CDR-All` pools selected RF observations using `LTE_RSRP`, `NR_RSRP`, `LTE_SINR`, `NR_SINR`, `Latitude` and `Longitude`, retaining Operator/Campaign context. |
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

Use one row without `Source Dataset` or KPI fields. A structural row cannot share its slide number with chart rows.

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
- `Histogram Line`
- `Histogram Bars`
- `Multi KPI CDF Lines`
- `Scatter`
- `Map`
- `Table`
- `Average Vertical Bars`
- `Median Vertical Bars`
- `Distribution Stacked Vertical Bars`
- `Threshold Stacked Vertical Bars`

Choose a KPI and at least one Rows or Column Aggregation dimension. `CDF Line` creates one curve per complete aggregation combination. Count charts retain empty combinations where required so comparisons remain aligned.

The RF Quality template includes combined Data/Voice/Speech slides before each chart family. Its `CDR-All` source is virtual: it uses the selected physical datasets and creates no duplicate CDR dataset or database table. Templates containing this source are retained by JSON/CSV import/export, workspace transfers and backup/restore.

`Histogram Bars` uses the same bins as `Histogram Line`, with side-by-side Campaign bars and lighter shades for older Campaigns. Paired LTE/NR rows can use a dynamic layout with `Dynamic Columns Field = Operator` to show all selected Operators on one slide.

`Histogram Line` draws an unfilled step contour for each aggregation combination. Set `Bin Size = 5` in Filters for 5-unit bins, or `Bin Size = 1` for 1-unit bins. The vertical axis shows the percentage of valid samples in each bin, normalized independently per series; series models retain sample counts. Histograms reuse CDF colours, progressive campaign widths and multivendor operator line patterns. Add four `Buckets = ...` thresholds for five red-to-green quality background bands. Add `Class Colours = Quality` to matching distribution charts to use those same five class colours. The existing template/JSON export, import and backup workflows preserve these chart settings.

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
Source Dataset: CDR-Voice
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
Source Dataset: CDR-Data
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
Source Dataset: CDR-Data
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
Source Dataset: CDR-Data
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
Source Dataset: CDR-Speech
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
Source Dataset: CDR-Data
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
Source Dataset: CDR-Speech
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
Source Dataset: CDR-Speech
KPI: LQ vs Playing_RSRP_NR_Avg
Chart type: Scatter
Filters: Call_Status = Completed; Call Family = WhatsApp
Rows Aggregation: Operator
Column Aggregation: Campaign
Legend Position: Bottom
```

#### Map

Use latitude and longitude in `Latitude vs Longitude` order. Aggregations and legend determine point grouping and colour.

To colour a radio-quality map by a measured value, use `Latitude vs Longitude vs Measure`, set **Rows Aggregation** and **Legend** to `Value Bucket`, and define four ascending thresholds with `Buckets = ...`. For example, RSRP uses `Buckets = -110,-100,-90,-80`, and SINR uses `Buckets = 0,5,13,20`. These five ranges use red, orange, yellow, light green and green. Missing measurements are excluded when **Exclude Null/Empty** is enabled. Two-field maps retain their existing grouping colours.

```text
Source Dataset: CDR-Data
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
Source Dataset: CDR-Voice
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
Call Family IN (VoLTE, MultiRAB); Direction = DL; Vendor NOT CONTAINS (Mixed, Other)
```

| Operator | Example |
| --- | --- |
| Equals / not equal | `Call_Status = Completed`, `Operator != EE` |
| List inclusion / exclusion | `Operator IN (VF, O2, 3, EE)`, `Campaign NOT IN (2025-Q4)` |
| Contains / not contains | `Test_Name CONTAINS FDFS`, `Vendor NOT CONTAINS (Mixed, Other)` |
| Numeric comparison | `LQ < 1.6`, `Mean_Data_Rate >= 20` |

`Vendor` filters the vendor alone and `Operator_Vendor` the `<Operator>_<Vendor>` identity. Import accepts the former `Vendor_Only` and `Vendor V3` (as `Vendor`) and `OP_Vendor` (as `Operator_Vendor`) filter names, and templates written for earlier versions are converted once: their `Vendor` groupings and legends become `Operator_Vendor` and their `Vendor_Only` filters become `Vendor`, so their charts stay identical. Operator-prefixed filter values are resolved using workspace operator aliases when the report runs. This alias handling applies to filter fields, while aggregation fields keep their selected comparison semantics.

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

## Mappings & Reference Data

The Mappings & Reference Data panel contains Operator Maps, Vendor Maps, Campaign Maps, Map Areas and Spectrum Holdings as independently collapsible subpanels. Their light blue headers distinguish them from the dark parent header. Existing mapping controls and saved expansion states remain available inside each subpanel.

### Operator Maps

Operator Maps set how the Operators are named, ordered and coloured in every filter, table, chart, legend and report. They have two numbered subpanels, each of which can be collapsed (the browser remembers it):

**1 · Operator names found in the CDRs** lists every Operator name of the ready CDRs of the workspace, with the number of CDRs that contain it (hover it to see their names), its **Label** and its **Status**:

- **Unassigned** (red, and the number of the subpanel turns red): the name has no label yet, so it is shown as it is and never added up with other names. **Use own names** gives every unassigned name a new label with its own name.
- **Merges N**: the label stands for N names of the CDRs, which are added up as one Operator (hover it to see the others).
- **Assigned**: the label stands for this name only.

Choose the label of each name in its list: one of the Operator labels of subpanel 2, or **+ New label…**, which lets you type a new label (Enter to accept, Esc to cancel) that every list then offers too. Press **Save assignments**; a new label is added at the end of subpanel 2. Each name therefore keeps its own label unless you give several names the same one: for example `Vodafone UK` → `VF`, `Vodafone SA` → `VF-SA` and `Vodafone VoNR` → `VF-VoNR` keep the three apart, while two spellings of the same network (`Vodafone` and `Vodafone UK`) can share `VF`. A name that is itself one of the labels (for example `EE`, shown as `EE`) cannot be changed here: rename that label in subpanel 2. Saving asks for confirmation when a label would add up names of the CDRs that it did not add up before, when a name leaves a label that saved filters or Reporting Jobs use (they no longer include it, and the dialog says how many use it), and when a new label contains `_`, which also separates Operator and Vendor in `Operator_Vendor` values such as `VF_Ericsson`.

**2 · Operator labels** lists one row per label with its **Order**, **Colour**, **Label**, **Possible names in the CDRs** and **Actions**. The possible names are how the label can be written in the CDRs of the different campaigns, shown as chips: highlighted with the number of CDRs when the current CDRs have them, grey when they are names of other campaigns, and ordered from the name in most CDRs (alphabetically when they tie). Hovering a chip, a CDRs count or a **Merges N** badge shows its CDRs or names at once; clicking it keeps them in a floating panel until it is closed (×, Esc or a click outside). **×** removes a name and **Add a name** with **+** adds one; a name of another label moves to this one at once. Under the label, **Merges N** tells that it adds up N names of the current CDRs. The label also stands for the name written like itself, so it need not be added. Saving a label asks for the same confirmation as subpanel 1.

Use **Add label** to create a label with its colour and possible names (one per line; comma and semicolon separators are accepted too). Change a label's name, possible names or colour and press **Save Labels**, below the table, to save every changed label at once (Enter in a label saves that one). **Move up** and **Move down** set its position in Operator charts and in Subscriber dimensions; the first and last rows cannot move beyond the table. **Delete** removes the label after confirmation, and its names are shown as they are until they get another label.

Renaming a label updates exact matching references in Report Templates and saved Dashboards, and the values of the Operator, Operator_Vendor, Vendor_Operator and Vendor filters saved in Reporting Jobs (including the GAP reference operator and the Scoring report scenarios), saved Scoring report configurations, the last Scoring calculation, the CDR Analysis filters of each CDR and the Non-Qualified Calls filters (`VF_UK` → `VF` also turns `VF_UK_Ericsson` into `VF_Ericsson` and `Ericsson_VF_UK` into `Ericsson_VF`). Campaign filters keep the full campaign value, so changing the Campaign Maps never requires renaming them.

The colour picker sets the label's chart theme colour; charts can derive related shades to distinguish campaigns or series. Every filter, table, chart, legend and report of the tool shows the label, and choosing it selects all its names; only Preview Dataset shows the names as they are in the CDRs.

The maps do not rewrite source workbooks, stored CDR rows or combined CDR tables. Saving, moving or deleting a label clears chart caches so later views use the new settings.

### Vendor Maps

Vendor Maps have the same two subpanels: **1 · Vendor names found in the CDRs** lists every Vendor name of the ready CDRs (the Operators without a Vendor, `<Operator> - All`, are not Vendors) and gives each one a label exactly as in the [Operator Maps](#operator-maps), and **2 · Vendor labels** has the same **Order**, **Colour**, **Label**, **Possible names in the CDRs** and **Actions** controls, with **Add label**, **Save Labels**, **Move up**, **Move down** and confirmed **Delete**. Names are matched without regard to case.

Renaming a Vendor label updates exact matching Report Template and saved Dashboard references, and the same saved filters as an Operator rename.

Vendor order determines the chart sequence for Vendor dimensions and the Vendor portion of combined `Operator_Vendor` values. The selected colour gives a Vendor a consistent chart identity, with related shades where multiple series need distinction. Every filter, table, chart and report shows the Vendor label (and the Operator and Vendor labels of an `Operator_Vendor`), and choosing it selects all its names; the maps do not alter materialized CDR values, which only Preview Dataset shows. Label changes refresh chart caches without rematerializing source data.

### Campaign Maps

Campaign Maps set how every chart, table, legend, filter and PowerPoint or Word report of the workspace names and orders campaigns. They follow a pattern rather than a list, so campaigns uploaded later, such as `2026-Q3` or `2027-Q1`, follow it without editing the map.

- **Label format** writes the label from the parts read in the campaign name: `{year}` (2026), `{yy}` (26), `{quarter}` (2), `{mode}` (SA or NSA) and `{market}` (the country code, such as UK). Characters inside the braces of a marker are written only when the campaign has that part: the default `{year}-Q{quarter}{-mode}` shows `UK_Q2_2026` as `2026-Q2` and `UK_Q2_SA_2026` as `2026-Q2-SA`.
- **Order inside a quarter** orders campaigns by year and quarter, and the campaigns of one quarter by mode: by default first the campaign without mode, then NSA, then SA. Use the arrows to change it.
- **Exceptions** give their own label to campaigns that do not follow the pattern, one or more source campaigns per label. They are ordered by the year and quarter of their label, after the campaigns of that quarter, or first, in the table order, when the label has none. Campaigns without a year and quarter and without an exception keep their name.

The **Preview** lists the campaigns of the ready CDRs of the workspace with the labels and order of the map being edited, and the **Status** of each one: **Unassigned** for a campaign without a year and quarter and without an exception (its **+** adds an exception for it, labelled with its own name to start with), **Merges N** when N campaigns share its label, which every filter, table, chart and report adds up as one campaign, and **Assigned** otherwise. Saving an exception that merges two or more campaigns of the CDRs asks for confirmation first. **Default map** fills the default map; **Save Campaign Maps** applies it and refreshes chart caches. Labels are only visual: filters, stored CDR values and saved selections keep the original campaigns.

### Unassigned values warning

While the ready CDRs of the workspace have Operators, Vendors or Campaigns that no map assigns, every page shows a red card at its lower right with the number of unassigned values and, for each kind, the first values (hover them to see all). It appears as soon as a processed CDR brings a new value and stays until every value is assigned; **−** minimizes it for the rest of the browser session. The user-editor, admin and super-admin roles have an **Assign Operators**, **Assign Vendors** or **Assign Campaigns** button that opens the names found in the CDRs of the matching map (or the Campaign Maps) in Workspace Config; the user-viewer role sees the card without the buttons and is asked to inform an administrator.

### Map Areas

Map Areas are the administrative areas the **Points Lost Map** of [Scoring & GAP Analysis](scoring-gap-analysis.md#points-lost-map) colours in each country of the tests, such as municipalities in Spain, counties in the USA or census divisions in Canada. The United Kingdom always uses the bundled ITL3 areas; every other country needs its own areas, and its tests are shown as bubbles until it has them.

- **Countries of the tests** lists the countries found in a sample of the coordinates of the ready CDRs, with their share of the tests and their Map Areas. **Choose areas…** lists the administrative levels that [geoBoundaries](https://www.geoboundaries.org) offers for the country, each with its number of areas and its licence; the suggested level is the finest one with up to 12,000 areas that allows commercial use, and levels whose licence does not allow it ask before downloading. **Download** saves the areas, simplified, in the workspace (a large country can take a minute). The server must be able to reach geoboundaries.org and github.com; otherwise import the areas from a file.
- **Saved Map Areas** lists one layer per country with its areas, source, licence and last update, and **Delete** removes it.
- **Import areas from a file** reads a GeoJSON, or a ZIP holding one Shapefile, with one polygon per area: give the country (ISO 3166 alpha-3 code, such as `ESP`), the name of the areas (such as *municipality*) and, when it is not detected, the attribute that holds their names. It replaces the saved areas of that country.

Areas with the same name in one country are numbered. Calculate the scoring again after adding or changing the areas of a country: each job keeps the polygons of the areas its tests are in and the outline of their countries. The Map Areas are stored in the **Map Area Layers** table, and travel with the Mappings & Reference Data in Import / Export, transfers and backups. Country borders: Natural Earth (public domain).

### Spectrum Holdings

Spectrum Holdings list the licensed spectrum of each Operator for the **Spectrum** panel of [Network Insights](network-insights.md#spectrum). Enter one band per row with the header `Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes`:

```text
Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes
Vodafone,B20,FDD,Low,20,2x10 MHz
Vodafone,n78,TDD,High (TDD),90,
```

- **Operator** should match a label of the Operator Maps.
- **Band** uses LTE (`B20`) or NR (`n78`) names.
- **Duplex** is `FDD`, `TDD` or `SDL`; **Band Class** is `Low`, `Mid` or `High (TDD)`. Both are inferred for known bands when left empty.
- **Bandwidth MHz** is the total bandwidth held, for example `20` for 2×10 MHz FDD.

Comma, semicolon and tab separators are accepted, so rows can be pasted from a spreadsheet. **Save Spectrum Holdings** validates every row and replaces all holdings of the workspace; an empty text area removes them. The table above the editor shows the MHz per Operator and band class.

## CDR type

The **Workspace Configuration** panel at the top chooses the **CDR type** of the workspace: the CDR files it processes. **NetCheck CDR** is the default and the only type supported today; **Umlaut CDR** files are similar but rename some columns, and appear as *coming soon* until they are supported. The type is also chosen when a workspace is created and can be changed from the workspaces table of [Workspace Management](workspace-management.md). It is stored in the workspace database, so it travels with the workspace in transfers, Full Workspace packages and backups.

## Main Cities

The Main Cities panel appears before Mappings & Reference Data and lists cities found in ready CDR datasets for the active workspace. Use the center buttons to move selected or all cities between the available list and the selected list, then choose **Save Main Cities**. The setting belongs to this workspace.

Every City selector — Dashboard filters, the PowerPoint export, Scoring, Network Insights, Non-Qualified Calls and Reporting Jobs — offers **Main Cities** as its first option. Applying it selects the configured cities that are available in the current selection.

## Portable operations

Administrators use Admin's existing **Import / Export / Transfer** and **Backup Protection** controls to move or restore workspace settings. Main Cities is a portable component alongside Report Templates and Mappings & Reference Data; full-workspace packages and database backups also retain the setting. The Mappings & Reference Data package (`mappings-reference-data/mappings-reference-data.json`) contains the Operator and Vendor Maps, Spectrum Holdings and Campaign Maps, and importing it replaces all of them in the destination workspace.

For global runtime settings, see [Application Config](app-config.md). Admin's [Database Viewer](administrator-config.md#database-viewer) documents the underlying Operator and Vendor mapping tables.

## Scoring & GAP Analysis Setup

A methodology defines the complete scoring setup: its title, environments, KPI definitions and weights and KPI priorities. Select or create a methodology before editing its settings. The aggregation hierarchy is an application setting ordered from the Aggregation levels of [Scoring & GAP Analysis](scoring-gap-analysis.md#3-set-filters-aggregation-and-reference), not part of a methodology.

### Methodology controls

| Action | Result |
| --- | --- |
| Create / Duplicate Methodology | Start a new definition or use an existing methodology as the basis for a revision. |
| Rename / edit title | Change the methodology identity or descriptive title. |
| Set Default | Choose the saved methodology initially offered for future scoring jobs. |
| Save Methodology | Validate and persist the complete methodology, including every subpanel. |
| Export Methodology (JSON) | Download the selected methodology only. |
| Import Methodology (JSON) | Import a portable methodology document. |
| Admin Export / Backup | Package every saved methodology and the default selection together. |

> [!IMPORTANT]
> **One save operation.** Save Methodology appears above the subpanels and inside each one for convenience. Every instance saves the same complete setup; there are no independent priority saves.

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
- KPIs whose **Type** is **Reliable** form the Most Reliable Network scoring, with the same thresholds: set their **Most Reliable points** in the selected environment (the column can only be edited on Reliable KPIs). The line above the table counts the Reliable KPIs and their points. See [Most Reliable Network scoring](scoring-gap-analysis.md#most-reliable-network-scoring).

Max Points displays two decimal places while retaining full precision for calculation and unchanged allocations when saved. The formula determines the calculation basis; formulas and filters must use supported engine fields and operations.

### Methodology KPIs Priorities for GAP analysis

Maintain the transferable KPI priority list with up/down, first/last or specific-position controls. The position must be a whole number from 1 to the number of KPIs; Enter applies it and Escape cancels.

> [!NOTE]
> **Priority and result ordering.** The saved priority list does not currently determine GAP result order. Individual comparisons sort signed GAP from lowest to highest, with unavailable values last; All Operators retains KPI definition order.

Web and PowerPoint GAP tables include a final sum for each comparison column. Individual PPT comparisons show Average KPI GAP and the average of the column GAP totals. These are distinct statistics; see the [complete Scoring & GAP Analysis guide](scoring-gap-analysis.md) for examples, coverage rules and JSON formats.


### Chart layouts

The editor offers **121 layouts**: every combination of **1–6 rows × 1–6 columns**, each without comments, with comments below, or with comments to the right (108 fixed grids), plus nine dynamic layouts and `Title Page`, `Title Only`, `Transition` and `Black logo end slide`. The physical layouts appear immediately after `Black Title Page` in the same order as the selector, excluding the virtual dynamic options.

Names follow `Title + N rows + M columns`, optionally followed by `+ comments down` or `+ comments right`. The 108 fixed grids and four structural layouts exist physically in the reference PPT. `Source Dataset = CDR-All` exposes the union of Data, Voice and Speech fields, including normalized RF fields and `CDR_Type`, in cell assistance. The nine dynamic options are virtual: the renderer selects a fixed grid from the distinct values of their row and column fields. The widened Layout cell-assistance selector lists Title Page, Title Only, Transition and Black logo end slide first, followed by the nine dynamic grids and then the fixed grids. Long names stay on one line; narrow screens can scroll horizontally. Structural layouts have blue shading, dynamic layouts purple shading and the selected option yellow shading; selection retains its position without a duplicate at the top. Other native layouts remain internal to structural slides. Historic layout names are normalized on import and in stored templates; exports use the canonical names. Grids without comments use the full chart area.

### Dynamic chart grids

CSV imports identify columns by name and accept them in any order; duplicate names or aliases are rejected. The editor and exported CSV place **Dynamic Rows Field** and **Dynamic Columns Field** immediately after **Layout**. Use these fields to choose which source field creates the rows and columns. A dynamic layout requires a non-empty field for each dynamic axis; the parser rejects missing fields. Leave the field for a fixed axis empty. CSV exports include both columns; template import/export, transfers, backup and restore preserve them. Older CSVs with `Dynamic Field` remain importable: its value is assigned to the dynamic axis declared by the layout.

| Layout | Repeated dimension | Commentary |
|---|---|---|
| `Title + 2 rows + dynamic columns` | Columns | None |
| `Title + 2 rows + dynamic columns + comments down` | Columns | Below |
| `Title + 2 rows + dynamic columns + comments right` | Columns | Right |
| `Title + dynamic rows + 2 columns` | Rows | None |
| `Title + dynamic rows + 2 columns + comments down` | Rows | Below |
| `Title + dynamic rows + 2 columns + comments right` | Rows | Right |
| `Title + dynamic rows + dynamic columns` | Rows and columns | None |
| `Title + dynamic rows + dynamic columns + comments down` | Rows and columns | Below |
| `Title + dynamic rows + dynamic columns + comments right` | Rows and columns | Right |

- **Two fixed rows:** use two chart definitions on the slide with the same Layout and Dynamic Columns Field. The first fills the top row and the second the bottom row.
- **Two fixed columns:** use two chart definitions with the same Layout and Dynamic Rows Field. The first fills the left column and the second the right column.
- **Both axes dynamic:** use one chart definition and two different fields, for example `Region` for rows and `Operator` for columns. Each chart includes only samples matching both values.

Distinct values come from the selected, filtered CDR universe; empty values are excluded. Both-axis grids paginate at six rows and six columns. Multivendor grids also paginate at six repeated values, keeping operators of the same vendor together where possible. Larger ordinary single-axis grids can be derived from the native geometry; charts become smaller as the grid grows.

> [!TIP]
> **Readability:** a 6 × 6 grid fits 36 charts, but gives each chart little space. Prefer fewer charts when labels or distributions need close inspection.

For RF histograms, select **Operator**: the first definition is LTE and the second NR, so each Operator occupies one column. Campaigns remain grouped inside each chart. Changing filters changes the number of columns; LTE and NR keep their corresponding positions even when one technology has no valid samples.

> [!NOTE]
> **Vendor comparison:** When **Report type** is **Multivendor Comparison**, the **Vendor comparison** selector appears to its right. **Vendor Only (All Operators Combined)** is the first and default option when opening the export dialog; it pools selected operators using the same `Vendor` value. Choose **Operator - Vendor** to keep each operator separate. Campaigns remain separate. The job retains this choice for retries. Dynamic vendor grids use up to six columns per slide and keep operators of the same vendor together where possible.

### Vendor-only filter labels

Across the application, values follow the Operator Maps and Vendor Maps order: `Vendor` lists pure vendors first, then the mixed, other and all-vendor groups, then the operators without a vendor; `Operator_Vendor` is ordered by Operator and, within one Operator, by Vendor; `Vendor_Operator` (`<Vendor>_<Operator>`) by Vendor and, within one Vendor, by Operator, with the mixed group of a vendor beside that vendor for each Operator (`Ericsson_3`, `Ericsson_Mixed_3`, `Ericsson_VF_UK`, `Ericsson_Mixed_VF_UK`) and the other mixed groups (`Non-Ericsson_Mixed`) last of all, after the operators without a vendor. In both, operators without a vendor (`<Operator> - All`) come last, in Operator Maps order, and values missing from the maps follow the mapped ones alphabetically. Operator-only identities follow with the display suffix ** - All**, based on canonical Operator identities, their configured aliases and cached CDR operators. Configured vendor identities take precedence, so actual vendors remain in the first group. Vendor mapping stores `Operator - All` in `Operator_Vendor` and `Vendor` for operator-only identities. Dataset exports, combined CDRs, transfers and backups preserve that value; legacy operator-only values without the suffix remain supported. This applies to Dashboard filters, Network Insights, data-preview column filters, Query Builder column filters and Report Template filter assistance.

CDR catalogue caches retain the `Operator_Vendor`, `Vendor`, `Region`, `Cluster`, `City`, `Campaign` and `Operator` universes. CDR processing refreshes them from their source columns, and catalogues of CDRs processed before Cluster existed are backfilled once. The caches remain part of workspace database backups and restores.

Operator mapping colours also apply to operators without a vendor in multivendor charts, including Vendor labels displayed as **Operator - All**. Vendor mapping colours apply to actual vendors.
