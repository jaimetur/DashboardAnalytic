# Administration

Admin centralises global configuration and active-workspace maintenance. The available actions depend on the signed-in role.

## Roles

- `admin`: create and manage ordinary users/admins, manage active-workspace templates and datasets, and export/import/transfer Dashboards, templates, fields and accessible workspaces.
- `super-admin`: create or modify super-admin accounts, assign workspace access, export App Config or Full Environment, and approve incoming server transfers.

An admin cannot modify a super-admin account or assign the super-admin role. The signed-in account cannot delete itself, and at least one active super-admin must remain.

## Create user and Users

Administrators can:

- create accounts;
- rename users;
- change or reset passwords;
- enable or disable accounts;
- assign permitted roles;
- manage workspace access where authorised;
- delete eligible accounts.

Only a super-admin can change workspace access. Leave a password field empty when an edit should preserve the current password. **Reset password** restores `super123`, `admin123` or `demo123` for the three bootstrap names and uses `Ericsson123` for another account; the dialog displays the resulting password so it can be changed or communicated securely.

## Report Templates Management

Templates belong to the active workspace and are stored in that workspace database's `report_templates` table. Import, export, backup and transfer packages serialize them as portable CSV files, but those files are package artifacts rather than the live source of record. Obsolete `slides-templates` directories are removed by the current migration and portability flows.

The **Operator Mappings** panel appears immediately below Report Templates Management. Its canonical labels and aliases can be exported, imported or transferred independently as one portable JSON component.

Available actions:

- New
- Import CSV
- Edit
- Rename
- Duplicate
- Change NSA/SA type
- Set Default
- Export
- Delete

**New Template** creates a blank NSA definition and opens it for editing. Import accepts a CSV name or derives it from the filename, can convert a legacy catalogue when prompted and requires explicit overwrite confirmation for a case-insensitive name collision. Rename saves inline; duplicate creates `- Copy`; and a non-default template can move between NSA and SA when no same-name target exists.

One template can be default for each technology within a workspace. Reporting initially selects that default but does not change it when a user chooses another template for one job. A default template cannot change type or be deleted until another template becomes default. New workspaces start without templates. The row Export action downloads that individual CSV; portable ZIP export is available under Import / Export / Transfer.

## Report Template Editor

**Edit** opens the selected template in a large dialog. The template selector and duplicate Admin heading are intentionally omitted from the embedded editor.

### Grid behaviour

- The table scrolls vertically and horizontally inside its viewport.
- The bottom action bar remains visible.
- Shared slide cells are visually merged across charts on the same slide.
- Row controls add, remove, reorder and preview chart definitions.
- **Re-Enumerate Slides** rewrites slide numbers into their current visual order.
- Edited cells use a light pastel-yellow background.
- Newly inserted text is highlighted more strongly.
- A successful save resets all change highlighting.

### Validation

- Manual cell edits are validated immediately.
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

**Save Template** validates and persists the complete grid atomically. Close, Escape and backdrop actions preserve the editor when unsaved changes still require a decision.

## Report Template reference

This is the canonical authoring reference for templates used by both [E2E Dashboards](07-e2e-dashboards.md) and [E2E Reporting](08-e2e-reporting.md). The common `assets/ppt-templates/Template_CDR_analysis.pptx` supplies the masters, named layouts and placeholders. Each distinct `Slide` value creates one slide; chart rows sharing that value fill its chart placeholders in row order.

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

For multi-chart slides, the editor visually groups `Slide`, `Slide Tittle`, `Slide Subtittle` and `Layout`; the CSV still stores them on every row.

### Structural slides

Use one row without `CDR source` or KPI fields. A structural row cannot share its slide number with chart rows.

- `Title Slide` normally uses `Title Page` and fills title/subtitle placeholders.
- `Transition Slide` normally uses `Title Only` and creates a section divider.

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

Use explicit numeric ranges. Add `Buckets` to Filters and use `Rate Bucket` as the final column aggregation.

```text
CDR source: CDR-Data
KPI: Mean_Data_Rate
Chart type: Distribution Stacked Vertical Bars
Filters: Test_Result = Completed; Test_Name CONTAINS FDTT; Buckets = 1,5,20,100
Rows Aggregation: Operator
Column Aggregation: Campaign × Rate Bucket
Legend Position: Right
```

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

Historical aliases resolve to `VF`, `O2`, `3` and `EE` for display without changing the source workbook. Vendor colour families are stable: Ericsson green, Huawei red, Samsung yellow and NSN blue; multiple operators using one vendor receive distinct shades.

## Import / Export / Transfer

### Export targets

- App Config
- Dashboards from the active workspace
- Report Templates from the active workspace
- Operator Mappings from the active workspace
- Auto-calculated Fields from the active workspace
- An accessible workspace
- Full Environment with selected workspaces

Admins can export/transfer the active workspace's Dashboards, Report Templates, Operator Mappings and Auto-calculated Fields, plus complete workspaces they can access. Super-admins can also export App Config and a Full Environment. Dashboard, template, mapping and field packages preselect a destination workspace with the same name as their source, where available, and allow one or more accessible destinations to be selected.

A Full Environment always contains App Config and the complete database/input content, Dashboard definitions, Report Templates, Operator Mappings and Auto-calculated Fields for every selected workspace. **Include generated Reports, Chart Sets and Dashboard PPT jobs** controls whether their `output/` trees are included. At least one workspace is required.

Exports run as disk-backed jobs and show estimated progress. The ZIP download starts when package creation finishes.

### Import workflow

1. Select a Dashboard Analytic ZIP and wait for its disk-backed upload.
2. Review the manifest-detected content, affected workspaces and overwrite warnings.
3. For Dashboard, Report Template, Operator Mapping or Auto-calculated Field packages, choose one or more accessible destination workspaces; a matching source name is preselected when available.
4. Confirm import.
5. Follow the background import in the floating task card.

Workspace replacement is automatic: the application closes the target when required, imports the replacement, and removes obsolete old files only after success.

### Transfer to other server

1. Choose **Content to export/transfer**.
2. Enter destination URL/IP and port; the default port is `7278`.
3. Press Enter or select **Connect and request approval**.
4. A destination super-admin accepts or rejects the offer.
5. Follow export creation and transmission at source.
6. Follow reception and automatic import at destination.

The dialog remembers the last destination. Active state is restored after page reload, resumable reception tolerates temporary connection cuts and contacting can be cancelled.

For super-admins, complete unimported packages appear in **Recovered transfer packages** with content, workspaces, creation time, size, Import and Delete actions. Incomplete remnants are removed automatically.

## Database Management

Database Management has two clearly separated subsections: **Backup Protection** and **Database Viewer**.

### Backup Protection

**Admin → Database Management → Backup Protection** separates **On demand backup** from **Scheduled backups**. On demand backup contains side-by-side **Backup** and **Restore** panels.

In **Backup**, select one or more content types:

- **Configuration Content: Application database** stores the shared application configuration.
- **Workspace Content: Workspace Database** stores the selected workspace SQLite databases.
- **Workspace Content: Dashboards** stores one JSON file with every Dashboard definition and its comments for each selected workspace.
- **Workspace Content: Report Templates** stores one CSV file for each Report Template.
- **Workspace Content: Operator Mappings** stores one JSON file containing every canonical label and alias.
- **Workspace Content: Auto-calculated Fields** stores one JSON file containing every selected workspace definition.
- **Workspace Content: Input** stores raw dataset files when explicitly selected.
- **Workspace Content: Output** stores generated Reports, Chart Sets and Dashboard PowerPoint jobs when explicitly selected.

Application database, Workspace Database, Dashboards, Report Templates, Operator Mappings and Auto-calculated Fields are selected by default. Input and Output are opt-in. Selecting any workspace content reveals **Workspaces to include**, containing only workspaces you can access. Dashboard, template and mapping JSON/CSV files use dedicated paths below `workspaces/<workspace name>/` in Backup and Export ZIPs; these portable paths are independent from the application's internal workspace folder name. Use **Backup folder** and **Browse** to choose the server-visible destination, then use **Backup Now** to create a ZIP in the background from the current content and workspace selection. Content, workspace and folder selections are saved for the scheduler without enabling it; the job appears in the floating background-task card and keeps the Admin panel in place.

In **Restore**, choose a server-visible **Backup folder** and one of its ZIP files. The application reads the selected backup's manifest to detect its granular content and affected workspace names, with a structural fallback for older ZIPs, then shows a structured overwrite confirmation grouped into **Configuration Content** and **Workspace Content**. Choose the individual parts to restore only after reviewing that existing data will be replaced. Restore work also runs in the floating background-task card. The ZIP selector refreshes after an immediate backup and periodically while Admin remains open, so completed scheduled backups appear without a page reload.

Enable the schedule to select hourly, daily, weekly or monthly execution. Weekly schedules expose a weekday selector and monthly schedules expose a day-of-month selector.

Set **Retention backups** to keep a maximum number of ZIPs; the scheduler removes the oldest successful backups after creating a newer one. The default storage directory is `APP_DATA_DIR/scheduled-backups`. **Browse** opens a server-side directory picker limited to `APP_DATA_DIR`, so it reflects directories visible to the host or Docker container rather than the browser's computer. It can create a folder before selecting it.

The status line reports the stored backup count and size, the most recent successful backup and the next scheduled run. Scheduled backups use the same chosen content and workspace selection as the Backup panel. Select Input and/or Output when raw datasets, Reports, Chart Sets or Dashboard PPT jobs must be included. Scheduled backups complement infrastructure backups and portable Export packages.

### Database Viewer

**Database Viewer** covers Application and Workspace Databases. It exposes global application-configuration tables, the active workspace database and the materialised combined CDR tables used to accelerate reporting; it is therefore broader than the active workspace alone.

Tables are grouped by ownership:

- **Config Tables**: global application configuration.
- **Workspace Tables**: templates, datasets, profiles, logs, workspace state, Dashboard selections, Dashboard selected rows, Dashboard PPT jobs and unified classic generated jobs.
- **Individual dataset rows**: one materialised table per dataset.
- **Combined CDR rows**: reporting acceleration tables by CDR type.

The **Generated jobs** table contains Report and Chart Set rows, distinguished by `job_type`. Dashboard PowerPoint history is stored separately in **Dashboard PPT jobs** because each row retains its Dashboard definition and applied filter snapshot.

The **Report Templates** table is the active workspace's `report_templates` table. It stores each template name, technology, default flag, timestamps and CSV content. Existing CSV templates are migrated automatically when their workspace is opened; compatibility CSV copies are generated only for portable packages.

The dedicated **Operator Mappings** panel loads every existing mapping from the active workspace and groups them by canonical Operator. Each row shows the editable canonical label beside every editable source label mapped to it; enter one alias per line, then save or delete the complete group. Use **Add canonical mapping** to create another group. The canonical label always maps to itself automatically. Mappings are applied only to temporary chart data and chart-template Operator filters. Individual and combined CDR tables, Dataset Preview filters, Dataset Analysis selectors and E2E Dashboard filters retain the exact source values. Changing a mapping invalidates chart caches but does not rematerialize CDRs.

Capabilities:

- 100-row server-side pagination with First/Previous/Next/Last;
- Excel-style distinct-value filters;
- active-filter chips;
- row editing and deletion;
- orphaned materialisation cleanup.

Saving or deleting a row clears analysis caches so later Dashboard and Reporting requests use the new value. Database edits affect the active workspace immediately. Use Export first when changing production data manually.

## Datasets Management

- Review dataset ID, editable name, stored path, uploader, upload time and last update.
- Rename a dataset inline; queued and processing rows remain locked until their current work finishes.
- Preview any Ready dataset in a separate tab.
- Open Ready Data, Voice or Speech CDRs in Datasets Analysis.
- Apply available VFUK/3UK mappings to an eligible CDR or clear its persisted Vendor mapping.
- Delete a dataset after confirmation whenever it is not processing; stop active processing from Workspace first.

Datasets Management appears below Database Management in Admin.

## App Logs

App Logs is a separate tab but supports administration and incident analysis.

- User filtering is case-insensitive.
- Usernames display in lowercase.
- **Executed by** distinguishes user steps from `system` steps.
- Login events include success/failure details.
- Only meaningful actions are recorded, not every click.

## Operational checklist

1. Replace bootstrap passwords.
2. Review workspace access periodically.
3. Back up configuration and data roots.
4. Test restoration with a non-production package.
5. Review App Logs after failures or permission changes.
6. Avoid manual Database Management edits unless the impact is understood.
