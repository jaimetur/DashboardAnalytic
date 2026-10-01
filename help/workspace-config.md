# Workspace Config

Workspace Config is a dedicated page for settings owned by the active workspace: Report Templates Management, Main Cities, Operator & Vendor Maps (Operator Maps and Vendor Maps), Scoring Aggregation Hierarchy, Scoring KPI Configuration and GAP KPI Priority. These settings remain workspace-scoped and are included in the applicable import, export, transfer, backup and restore workflows.

Open **Config → Workspace Config** from the main navigation at `/workspace-config`. Template, mapping and Main Cities actions use routes below `/workspace-config/`. The page uses the same teal/navy palette as Application Config and its Page Sections navigator links to the panels.

## Access and active workspace

The Workspace Config section is available to `user-editor`, `admin` and `super-admin` accounts. `user-viewer` accounts do not have access. Open a workspace before using its configuration panels; their contents and changes belong only to that workspace.

## Report Templates Management

Templates belong to the active workspace and are stored in that workspace database's `report_templates` table. Import, export, backup and transfer packages serialize them as portable CSV files, but those files are package artifacts rather than the live source of record. Obsolete `slides-templates` directories are removed by the current migration and portability flows.

Report Templates Management supports NSA and SA templates, one default for each technology, and the editor described below. Template names are unique per NR Mode, so an NSA and an SA template may share a name. The library is sorted by NR Mode (NSA first) and then name; its columns show the NR Mode, creation and last update times, and **Last Updated by**, the user who last imported, edited, renamed, duplicated, promoted or moved the template.

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

**New Template** creates a blank NSA definition and opens it for editing. Import accepts a CSV name or derives it from the filename, can convert a legacy catalogue when prompted and requires explicit overwrite confirmation for a case-insensitive name collision. Renaming saves when you leave the name field or press Enter; the field keeps its previous name and shows an error if the save fails. Duplicate creates `- Copy`; a non-default template can move between NSA and SA when no same-name target exists.

One template can be default for each technology within a workspace. Reporting initially selects that default but does not change it when a user chooses another template for one job. A default template cannot change type or be deleted until another template becomes default. New workspaces start without templates. The row Export action downloads that individual CSV; portable ZIP export is available under Import / Export / Transfer.

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

**Save Template** validates and persists the complete grid atomically. Dashboard comment reconciliation runs separately when slide identity changes; any required combined CDR update also runs after the save response. The Dashboard viewer refreshes the saved template when the editor closes. A combined CDR update is queued only when a template adds a source field missing from that CDR table. Removing the last template reference leaves the existing column available for future reuse. Close, Escape and backdrop actions preserve the editor when unsaved changes still require a decision.

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

Axis ranges are visual settings, not data filters, and are available to every chart family with a numeric axis. For example, `Axis X Range: [0.01,]` starts the horizontal axis at `0.01` while retaining its automatically calculated maximum; `[,30]` retains the automatic minimum and fixes the maximum at `30`. Empty range cells preserve the existing automatic behaviour. Percentage axes continue to use values from 0 to 100, while count, KPI, coordinate and scatter axes use their native units. Category axes and tables have no numeric domain to constrain.

`Label` is available to every chart family. For bars, `None` hides values, `Top` places them outside the bar, and `Up`, `Middle` and `Down` place them inside near the leading edge, centre or origin edge; horizontal bars map those directions to outside-right, inside-right, centre and inside-left. For CDF, scatter and map charts the same setting places point or endpoint labels around the plotted mark. An empty cell preserves each renderer's existing automatic behaviour.

`Exclude Null/Empty` and `Exclude Zero` are independent and apply to every chart family. For scatter charts the exclusions are checked on both plotted axes; for CDF and Multi KPI CDF charts they are checked on each plotted metric before the cumulative distribution is calculated. This allows a CDF to begin at its first non-zero observation instead of merely hiding the zero-valued section with an axis range.

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

Explicit ranges such as `Buckets = 1,5,20` produce `<1`, `1-5`, `5-20` and `20+`. Stacked segments and legend entries always follow ascending numeric order, regardless of the order in which values appear in the CDR rows.

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

The Operator & Vendor Maps panel contains Operator Maps and Vendor Maps as independently collapsible subpanels. Their light blue headers distinguish them from the dark parent header. Existing mapping controls and saved expansion states remain available inside each subpanel.

### Operator Maps

The table groups raw Operator labels under one canonical identity for charts. Each row shows **Order**, **Colour**, **Canonical label**, **Mapped source labels** and **Actions**. Enter source aliases one per line; comma and semicolon separators are accepted too. The canonical label also maps to itself automatically, so it need not be repeated among the aliases. An alias cannot belong to two canonical groups.

Use **Add canonical mapping** to create a group. Change its label, aliases or colour and press **Save** to update it. **Move up** and **Move down** set its position in Operator charts and in Subscriber dimensions; the first and last rows cannot move beyond the table. **Delete** removes the entire group, including its aliases, after confirmation. Canonical renames update exact matching references in Report Templates and saved Dashboards.

The colour picker sets the group's chart theme colour; charts can derive related shades to distinguish campaigns or series. Order and colour are presentation choices, while aliases make source labels such as `Vodafone UK` resolve to the intended canonical Operator. These settings affect chart grouping, legends and template filters. They do not rewrite source workbooks, stored CDR rows or combined CDR tables. Saving, moving or deleting a group clears chart caches so later views use the new settings.

### Vendor Maps

The Vendor table has the same **Order**, **Colour**, **Canonical label**, **Mapped source labels** and **Actions** controls. Use **Add canonical mapping**, **Save**, **Move up**, **Move down** or confirmed **Delete** to manage a Vendor and all its aliases. Alias matching is case-insensitive, the canonical label maps to itself, and an alias cannot belong to two Vendor groups. Renaming a canonical Vendor updates exact matching Report Template and saved Dashboard references.

Vendor order determines the chart sequence for Vendor dimensions and the Vendor portion of combined `Operator_Vendor` categories. The selected colour gives a Vendor a consistent chart identity, with related shades where multiple series need distinction. Aliases reconcile different source spellings for chart display and filters; they do not alter materialized CDR values. Group changes refresh chart caches without rematerializing source data.

## Main Cities

The Main Cities panel appears before Operator & Vendor Maps and lists cities found in ready CDR datasets for the active workspace. Use the center buttons to move selected or all cities between the available list and the selected list, then choose **Save Main Cities**. The setting belongs to this workspace.

Dashboard's Default Filters City multiselect and the PowerPoint export City selector provide a **Main Cities** preset. Applying it selects the configured cities that are available in the current Dashboard or export dataset selection.

## Portable operations

Administrators use Admin's existing **Import / Export / Transfer** and **Backup Protection** controls to move or restore workspace settings. Main Cities is a portable component alongside Report Templates and Operator & Vendor Maps; full-workspace packages and database backups also retain the setting.

For global runtime settings, see [Application Config](app-config.md). Admin's [Database Viewer](administrator-config.md#database-viewer) documents the underlying Operator and Vendor mapping tables.

## Scoring & GAP Analysis Setup

The main Scoring & GAP Analysis Setup panel contains three subpanels with light blue headers, visually distinct from the dark main panel header. Scoring KPI Configuration comes first, followed by Scoring Aggregation Hierarchy and GAP KPI Priority. Reorder Operator, Vendor, Region, City and Campaign using the arrows; save the complete hierarchy. The default is Operator → Vendor → Region → City → Campaign. It controls the filter/aggregation panel order and hierarchical tables, charts and PPT outputs of new jobs. Operator remains mandatory for calculations wherever it appears in the chosen hierarchy. An unconfigured workspace requires an explicit import via **Import JSON** or Admin; **Export JSON** uses the same portable document format as the JSON inside configuration ZIP packages. Select a named methodology, create a copy for a new revision and activate the profile used by future jobs. Select an environment and edit the category-grouped KPIs: category, label, source CDR type, direction, mapping method, formula, filter JSON, thresholds, KPI type and score interpolation anchors. Mapping is a separate KPI-level selector with Linear, Quadratic and Smooth curve; existing profiles default to Linear. The method is retained in JSON/ZIP exchanges, transfers and backups. Use the row Actions to add a KPI directly below that row in its category or move it up/down within that category. Add Category creates a named category with its first zero-point KPI; configure it before saving. Category is a dropdown of the methodology's current categories, allowing existing KPIs to move between groups. New definitions receive stable K-number identifiers; deleting or moving a row does not renumber the remaining definitions. Renaming a code in the table automatically updates its GAP priority reference when saved, without changing its priority. Add, delete or replace KPI definitions; at least one KPI must remain. The KPI Definition column's yellow pencil opens Edit formula and filters in a larger centered dialog with colored source/formula/filter sections; closing it retains draft edits until the configuration is saved. Calculation basis is read-only information derived from the formula, which controls the actual calculation; packet-loss expression controls appear only for the formula that uses them, with usage help. Category rows show summed points, relative Environment weights and global weights as separate green, blue and violet badges. KPI names are bold in a wider column and use one line when they fit and grow automatically for longer labels; fixed Ultra values can require a second row. Category names are highlighted badges. Circular SVG Actions stay on one row with tooltips and distinct colors: green for insertion, blue for moving and red for deletion. Max Points displays two decimal places while retaining full allocation precision for calculations and unchanged values when saving. Choose Points to change absolute allocations or Weight (%) to edit relative KPI weights, preserve the Environment total and redistribute other KPI weights proportionally. Edit the Environment allocation above the table; changing its global percentage preserves the grand total and redistributes other Environments. Create Environment opens a dialog for name, reference Environment, total points and source values `G_Level_1` / optional `G_Level_2`; it copies each KPI's rules and proportions from the reference, while the entered source values determine the CDR rows. Delete Environment removes the selected context from every KPI; keep at least one Environment with a positive overall allocation. Source values remain editable; overlapping source selections are rejected. These are draft changes until saved. Distribute points keeping percentages opens a viewport-centered dialog with a light backdrop to assign the selected Environment a chosen point total using the relative KPI weights of a reference Environment; review and save the draft. It does not copy thresholds or formulas. NetCheck 2026 includes Walk with zero points and editable relative weights. Colored column blocks distinguish points/weights (green), thresholds (amber), score mappings (violet) and identity/calculation (blue). Ultra may be absent, numeric or derived from the best minimum/maximum KPI in the comparison context. The workspace database is the authoritative source. Editable formulas and filters are checked against supported engine fields and operations; reference files are never loaded automatically. Save validates the complete configuration; invalid settings do not replace the saved configuration.

The header separates Methodology controls (profiles and portable operations) from Environment controls (selection, creation/renaming/deletion, points/weights, source matching and point distribution); a disclosure explains how points and weights work. The panels fit the available page width. The compact KPI table uses smaller fonts, balanced widths and darker grouped threshold/mapping headers, with Environment Weight (%) as the relative weight column and a centered KPI Definition pencil. Methodology controls have vertical spacing and explicit Rename Profile/Delete Profile labels; Profile and Environment deletion buttons are red; Export JSON is blue, Distribute points keeping percentages is violet and the formula editor Close button has a contrasting label. Environment allocation controls align their labels, and source guidance appears below the matching fields. On narrow panels it switches to labeled KPI cards to avoid horizontal scrolling; formula editing remains in a separate dialog. Operator and Vendor Maps give mapped source labels more space than canonical labels, and their creation forms put Colour first with aligned field labels.

GAP KPI Priority includes the category of each KPI and preserves an editable, transferable priority list. This list currently does not control GAP results or PowerPoint ordering: individual comparisons use signed GAP from highest to lowest, with unavailable values last; comparisons with multiple operators retain the default KPI definition order. GAP Category cells group consecutive rows only, and each full-category subtotal appears after its last KPI. Historical jobs retain their configuration snapshot; a changed configuration generates a new calculation/cache identity. Operator labels, order and colors continue to come from Operator Mappings.

Use the Scoring & GAP Analysis Configuration component in Import / Export / Transfer to move all saved profiles, their active selection, KPI definitions, aggregation hierarchy and GAP KPI priorities together. Main Cities appears before Operator & Vendor Maps in both Export and Backup selectors. Version-2 exports include the collection; legacy single-configuration packages remain importable. They are included in configuration backups and full workspace database backups and restored within the destination workspace. See [Scoring & GAP Analysis](scoring-gap-analysis.md) for interpolation, coverage, results and exports.
