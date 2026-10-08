# Workspace Management

Workspace Management is the first operational module. It controls isolated workspaces, their storage, dataset ingestion, processing queue and vendor mapping workflows.

> [!IMPORTANT]
> **Ready data first.** Wait for CDR processing to finish before analysis. A detected input type and a completed upload do not mean the dataset is ready.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Workspace Lifecycle | [Open section](#workspace-lifecycle) |
| Data Ingestion | [Open section](#data-ingestion) |
| NetCheck CDR Support | [Open section](#netcheck-cdr-support) |
| Dataset Inspection and Enrichment | [Open section](#dataset-inspection-and-enrichment) |
| Troubleshooting | [Open section](#troubleshooting) |

## Workspace Lifecycle

- Create, open, close, rename, duplicate and delete workspaces. **Create and open** asks for the name, the **CDR type** (NetCheck CDR by default; Umlaut CDR is coming soon) and, for super-admins, the **Access**, all in one row.
- Review workspace size, CDR type and access. The workspaces table changes the **CDR Type** of a workspace, and super-admins grant each workspace in its **Access** selector to roles, user groups and users; **✓** saves the row. Admins also grant workspaces in [Admin → Workspace Access](administrator-config.md#workspace-access).
- Keep databases, uploaded files and generated output isolated.
- Open a workspace before using Dashboard, Reporting or Chart Builder.

## Data Ingestion

Workspace accepts `CSV`, `XLS`, `XLSX` and `XLSM` for tabular datasets, and `GeoJSON`, `JSON` or zipped shapefiles for Regions, Clusters and Vendors. Only successfully processed datasets can be used by Dashboard, Chart Builder or Reporting.

### Supported Input Types

- CDR-Data
- CDR-Voice
- CDR-Speech
- Multivendor Mapping — VFUK
- Multivendor Mapping — 3UK
- Network Inventory — the cell inventory of any Operator, in any tabular layout
- Regions — Geospatial
- Clusters — Geospatial
- Vendors — Geospatial
- Smart Orchestrator Logs — listed for forward compatibility; ingestion and analysis are not yet implemented.
- Other supported dataset — offered on upload, and as **Other Datasets** in the Dataset Type filter, only while the workspace has such datasets.

### Upload Workflow

1. Open the target workspace.
2. Select one or more files in **Data Ingestion**.
3. Review the proposed type for every file.
4. For CDRs, review the proposed **NR Mode** (NSA or SA) and **CDR Type** (Final or Daily) and optionally choose the Vendor source and the ready VFUK/3UK, Regions and Clusters mappings. For Vendor polygons, review their **Operator**.
5. Confirm the batch.
6. Follow every item in **Queue and Status**.
7. Continue only when the status is **Processed**.

Classification is proposed from filenames but remains reviewable. Examples:

- `NetCheck_CDR_Data_2026_Q2.xlsx` → CDR-Data
- `NetCheck_CDR_Voice_2026_Q2.xlsx` → CDR-Voice
- `VFUK_Multivendor_Mapping.xlsx` → VFUK mapping

### Cluster polygons

Choose **Clusters — Geospatial** for cluster boundary files. It accepts the same geospatial formats as Regions: `.geojson`, `.json` or a `.zip` containing exactly one `.shp` and its required companion files (`.shx`, `.dbf`, and `.prj` to declare its coordinate reference system). The upload proposes Clusters for geospatial filenames containing `cluster`; the type remains editable before confirmation.

Cluster files must contain non-empty, valid Polygon or MultiPolygon geometries with a coordinate reference system and non-blank names in `Cluster`, `Cluster_ID`, `Cluster_Name`, `ClusterName` or `Name`. Validation registers the dataset as Processed, with no CDR NR Mode or KPI analysis. Preview draws its polygons on a map (see [Dataset Preview](#dataset-preview)); the original polygon file remains in the workspace input directory. Clusters appear in the Dataset Type filter and their metadata table is available in Database Management.

Cluster polygons are the required input shown in **Network Insights → Cluster Sites Density**. Importing them does not yet calculate site density. Scoring & GAP Analysis draws the **Points Lost Map** per Cluster (and per Region with Regions) on the polygons applied to the scored CDRs. Like Regions, they can be applied to CDRs: the **Cluster mapping** selector beside each CDR when importing (the newest ready Clusters dataset is proposed) and the **Cluster Mapping** field of the Map dialog (shown disabled, with a note, until the workspace has a ready Clusters dataset; Regions behave the same way) fill the CDR `Cluster` column with the name of the polygon containing each sample. Existing non-empty `Cluster` values from the source CDR are kept, and samples without coordinates or outside every polygon stay empty. They are preserved by workspace duplication, export/import, transfer and backup/restore when workspace data and input files are included. Database-only backups retain registration metadata but require the original input files to recover the polygons.

### Network Inventories

Choose **Network Inventory** for the cell inventory of any Operator, whatever its layout: it is stored like any other dataset and listed in the **Network Inventory & Vendor Mappings** card with its **Operator**, proposed from the file name (for example `O2_Network_Inventory.csv` → O2) and changeable in the card. The upload proposes Network Inventory for tabular filenames containing `inventory`.

When it has a Vendor column (`Vendor`, `OP/ Vendor`, `OP_Vendor`, `OEM`, `Manufacturer` or `Supplier`) and a cell identifier — a global one (`GCID`, `Global Cell ID`, `ECI`, `NCI`, `ECGI`, `NCGI`, `CGI`, `Cell Identity` or `Cell ID`) or an `eNodeB ID`/`gNodeB ID` with its `Local Cell ID` (`eNodeB × 256 + cell`, `gNodeB × 4096 + cell`) — it also maps the Vendor of its Operator's CDR samples (see [Vendor Mapping](#vendor-mapping)).

### Vendor polygons

Choose **Vendors — Geospatial** for polygons that give the Vendor of an area, so that CDRs can be mapped to Vendors without a Network Inventory, for any Operator. They accept the same formats as Clusters and need a non-blank `Vendor`, `OP_Vendor`, `OP/ Vendor` or `Name` attribute. The upload proposes Vendors for geospatial filenames containing `vendor`.

Each polygon belongs to one Operator:

- the **Operator** chosen on upload, proposed from the file name (for example `O2_Vendor_Polygons.geojson` → O2), so there can be one file per Operator;
- or, with **Multi-operator**, the `Operator` (or `MNO`, `Network`) attribute of each polygon, so one file can hold the Vendors of every Operator.

The Geographic Datasets card shows the **Type** of every shape (Regions, Clusters or Vendors) and, for Vendors, their Operator in a pill that changes it when it was assigned wrongly; map the CDRs again to apply the change.

How a CDR takes its Vendor from them is described in [Vendor Mapping](#vendor-mapping); Preview draws them on a map named `<Operator> · <Vendor>`.

### NR Mode

Every CDR (Data, Voice or Speech) belongs to one NR Mode, **NSA** or **SA**; other dataset types have none. During upload the NR Mode is proposed from the filename and can be changed per file before processing starts:

- `SA`, `5G SA`, `5GSA` or `Standalone` in the name (for example `UK_Q2_2026_SA_Data.xlsx`) → SA
- `NSA`, `Non-Standalone` or no NR indication (for example `NetCheck_CDR_Data_2026_Q2.xlsx`) → NSA

The **NR Mode** column follows Input Type in the Datasets table. Its selector corrects the NR Mode of an existing CDR without reprocessing it, and the change is recorded in App Logs. CDRs created before this column existed receive the filename proposal automatically. E2E Dashboards only use CDRs of their own NR Mode.

### CDR Type: Final and Daily

Every CDR is a **Final** CDR, delivered after its measurement campaign, or a **Daily** CDR, received while the campaign runs, either incremental (the calls of one day) or cumulative (every call so far). During upload the CDR Type is proposed from the filename and can be changed per file before processing starts:

- `Final` in the name → Final, even when it also has a date.
- `Daily`, `Diario`, `Day`, `Incremental` or `Cumulative` in the name → Daily.
- A date range (two different dates, for example `20250903-20251011`) → Final.
- A single date that is not the export date at the start of the name (`UK_Voice_CDR_20260921.xlsx`) → Daily; `20260921_UK_Voice.xlsx` → Final.
- Anything else → Final. The CDRs uploaded before Daily CDRs existed are Final CDRs.

The **CDR Type** selector of the Final and Daily CDR tables changes it without reprocessing the CDR, moves the CDR to the other table and is recorded in App Logs.

The **In Combined?** column holds the choice (**Auto**, the default, **Yes** or **No**) and, below it, whether the combined CDR tables include the CDR (**Yes** or **No**) and why. Each CDR shows one reason, the first of these that applies:

| Reason | When it applies | Included |
|---|---|---|
| *Included manually* / *Excluded manually* | The choice is **Yes** or **No**. It overrides every other rule, for Final and Daily CDRs alike. | As chosen |
| *Final CDRs are always included* | A Final CDR set to **Auto**. A Final CDR only leaves the combined tables when it is set to **No**. | Yes |
| *Replaced by the Final CDR …* | A Daily CDR set to **Auto** covered by a Final CDR that is included (not set to **No**), of the same type (Data, Voice or Speech), of the same NR Mode (or either has none) and that shares at least one `Campaign` value with it. The reason names that Final CDR. | No |
| *Every call is in the newer Daily CDR …* | A Daily CDR set to **Auto** with no Final CDR yet, when the newest Daily CDR of the same type, NR Mode and campaign (by the date of its data) contains every one of its calls (`JOIN_ID`). This is how a cumulative Daily CDR replaces the previous ones; incremental Daily CDRs, each with its own calls, are all included. | No |
| *No Final CDR of its campaign yet* | Any other Daily CDR set to **Auto**: it is the best data available while the campaign runs. | Yes |

A CDR left out stays in the Workspace and in CDR Analysis; only the combined tables leave it out. Setting a Final CDR to **No** stops it covering its Daily CDRs, which come back with the last two reasons.

For example, for the Voice SA CDRs of the campaign UK Q3, with cumulative Daily CDRs:

| CDR | CDR Type | In Combined? | Included | Reason |
|---|---|---|---|---|
| `UK_Voice_20260921.xlsx` | Daily | Auto | No | *Every call is in the newer Daily CDR UK_Voice_20260922.xlsx* |
| `UK_Voice_20260922.xlsx` | Daily | Auto | Yes | *No Final CDR of its campaign yet* |

When the Final CDR of the campaign arrives:

| CDR | CDR Type | In Combined? | Included | Reason |
|---|---|---|---|---|
| `UK_Voice_Q3_Final.xlsx` | Final | Auto | Yes | *Final CDRs are always included* |
| `UK_Voice_20260921.xlsx` | Daily | Auto | No | *Replaced by the Final CDR UK_Voice_Q3_Final.xlsx* |
| `UK_Voice_20260922.xlsx` | Daily | Auto | No | *Replaced by the Final CDR UK_Voice_Q3_Final.xlsx* |
| `UK_Voice_20260923.xlsx` | Daily | Yes | Yes | *Included manually* |

**Yes** and **No** include or exclude the CDR by hand. The rows of the CDRs that the combined tables include have a light green background and the others a light grey one. The **Yes**/**No** answer and the colour change at once and the combined tables follow every change in a background job listed in [CDR Tables Updates](#cdr-tables-updates) — a new CDR, a CDR Type, NR Mode or In Combined? choice, or a deleted CDR (deleting a Final CDR brings back the Daily CDRs it replaced) — so E2E Dashboards, Network Insights, Scoring & GAP Analysis and Reporting can use the Daily CDRs while the campaign runs and the Final CDRs when they arrive. Scoring & GAP Analysis, E2E Dashboards and the CDRs chosen automatically by Reporting Jobs offer the CDRs that the combined tables include. CDR Analysis opens any CDR, and [Non-Qualified Calls](non-qualified-calls.md#daily-and-final-cdrs) reads every CDR and lists each call once.

### Background Processing

Ready CDRs queue default Operator scoring when compatible companion CDRs are available. Open [Scoring & GAP Analysis](scoring-gap-analysis.md) to select one CDR of each type, filter cached Region/City/Operator/Vendor/Campaign values (including Main Cities), choose aggregations, consult saved results and export CSV/PPT files.

- A queued import retains its target workspace even if the user switches workspace.
- Processing continues after sign-out.
- Stop requests are cooperative.
- Failed or stopped work can be retried.
- Re-uploading the same stored dataset preserves its original upload date.
- Updated time records the latest processing operation.

The global floating task cards remain visible while workspace work continues. The open workspace is shown at the lower right; other accessible workspaces are shown at the lower left. Use **Stop Job** only when it is available and after reviewing the confirmation: a stopped duplication removes the incomplete copy, while a stopped import is rejected once file import has started.

## NetCheck CDR Support

### Source File and Worksheet Processing

- Every dataset keeps one CDR type: Data, Voice or Speech. Rows and fields from different CDR types are never combined in the same persisted CDR table.
- The contiguous operator worksheet block is read and stacked by rows. Identically named fields from different operator sheets align in one column; they do not create duplicate columns.
- Known summary, ranking, definition, list and helper worksheets are ignored. `Source_File`, `Source_Sheet` and `Dataset_Kind` record the origin of every persisted row.
- Source headers are preserved. Field resolution ignores letter case and separators such as spaces, underscores and hyphens; `Subscriber` and legacy `Suscriber` identify the same field.
- A genuinely repeated header within one source worksheet receives `_Duplicate_2`, `_Duplicate_3`, and so on. Empty source headers receive a positional `Unnamed_N` name. Technical SQLite collision suffixes such as `__2` are not retained.

### Datasets cards

The **Datasets** panel groups the datasets in cards, each with its icon, its own count and a sortable table; the times of the dates are shown in blue:

- **Final CDRs** and **Daily CDRs** (which folds), at full width, with the CDR Type and In Combined? columns; Rows sit above Columns and Uploaded above Updated in one column each, and each of them keeps its own sort button in the header.
- **Network Inventory & Vendor Mappings** (the network inventory of each operator: every cell with its vendor, site and configuration) and **Geographic Datasets** (Region, Cluster and Vendor polygons, with their **Type**), side by side with compact tables: dataset and type, rows, status with progress, last update and actions. Reference datasets have no analysis or mappings to apply, so their actions are **Preview**, **Reprocess** and **Delete**.
- **Other Datasets** (Smart Orchestrator logs and other supported datasets), when there are any.
- **Combined CDR tables**, the generated read-only query sources, with their Rows over Columns, status (**Ready**, **Updating**, **Recalculating**, **Queued**, **Missing Rows** or **Recalc Needed**), progress and last update; they mix NR Modes and come from no file, so they have no NR Mode, Size or Uploaded columns.

The **Dataset Type** filter and the bulk actions above the cards apply to every card; a filter hides the cards without datasets of that type.

### Combined Table Recreation

The Datasets tables show comma-grouped Rows and Columns for each individual and combined dataset. Combined tables cannot be imported separately: CDR processing creates them from the ready individual CDRs of the same type that they include (see [CDR Type](#cdr-type-final-and-daily)).

The circular **Recreate combined table** action checks every ready individual CDR of that type that the table includes in the background before rebuilding the combined table. If an individual table uses an older normalization version, the job migrates it from its original source file first; one recreation each for Data, Voice and Speech therefore upgrades both their individual and combined tables.

Its live task detail identifies the individual table being migrated. Opening a combined preview performs the same compatibility check, and its Loading Dataset panel explains when all individual tables of that CDR type may need migration.

### CDR Tables Updates

The **CDR Tables Updates** card, below the Datasets cards, lists the background jobs that rewrite the CDR tables, each with its own label, message and progress bar:

- **Auto-calculated Fields**: saving, importing or rematerializing auto-calculated fields (**Re-materialize All Fields** in the Auto-calculated Fields panel).
- **Combined CDR-DATA**, **-VOICE** or **-SPEECH**: recreating a combined table, after a CDR is processed or mapped, or with **Recreate combined table**.
- **Combined CDR tables**: bringing the combined tables in line with a CDR Type, NR Mode or In Combined? change or a deleted CDR.
- **CDR tables reconciliation**: the automatic check when a workspace opens with pending work or a report template needs new columns.

Its pills sum up the state (**Up to date**, **N in progress**, **N queued**). With nothing to do it reads *All CDR tables are up to date*. While auto-calculated fields are materialized, the Auto-calculated Fields panel shows their progress with a link to this card. Whenever a job starts, changes state or ends, the Datasets cards, the combined CDR tables included, refresh their counts, status, progress and Updated values in place without reloading the Workspace page.

### Fixed CDR Fields

The processor materialises every fixed field even when all its values are empty. Dataset Preview places them after `Source_File`, `Source_Sheet` and `Dataset_Kind` in the order shown below. Each field follows its own rule:

| Field | Stored value / fallback rule |
| --- | --- |
| `Operator` | Imports and preserves the source `Operator`, `Operator_A`, `Home_Operator_A` or `Home_Operator` value. Every filter, table, chart and report shows it with its Operator Maps label, and a mapped selection matches every source spelling; only Dataset Preview and the stored CDR tables keep the source value. |
| `Subscriber` | Keeps the source `Subscriber` or legacy `Suscriber` value. If the complete field is absent or empty, it copies `Operator`. |
| `Vendor` | Stores `Operator_Vendor` for operators resolved through a multivendor cell mapping and the canonical `Operator` for all other operators. This is the single official comparison field used by filters, legends and reports. |
| `Operator_Vendor` | The `<Operator>_<Vendor>` identity from the source CDR or the vendor mapping (`<Operator> - All` for operators without a vendor). |
| `Vendor` | The vendor alone: `Operator_Vendor` without a recognised operator prefix, including configured Vodafone/VF, Three/3/H3G, O2 and EE aliases (`<Operator> - All` for operators without a vendor). |
| `Campaign` | Keeps the exact source value. Comparisons and chart labels recognise reordered country, year, quarter and SA/NSA tokens and can present `YYYY-Qn`, `YYYY-Qn_SA` or `YYYY-Qn_NSA`. A mode-free equality filter does not merge SA and NSA records. |
| `Benchmark` | Keeps the source value. If the complete source column is absent or empty, it copies `Campaign`. |
| `Campaign_Year` | Extracts the first four-digit year from `Campaign`, using `Benchmark` as the per-row fallback. |
| `Campaign_Quarter` | Extracts `Q1`, `Q2`, `Q3` or `Q4` from `Campaign`, using `Benchmark` as the per-row fallback. |
| `Period` | Joins `Campaign_Year` and `Campaign_Quarter` as `YYYY-Qn`. |
| `Market` | Recognises a delimited ISO country code or English country name in `Campaign`, then in `Benchmark`, and stores the two-letter code. |
| `Region` | Keeps the source value and remains empty when the source field is absent. |
| `Zone` | Keeps the source value; otherwise copies `G_Level_3`; otherwise remains empty. |
| `City` | Keeps the source value; otherwise copies `G_Level_4`; otherwise remains empty. |
| `Technology` | Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Technology`, `RAT`, `RAT_A`, `L2_Call_Mode_A` and `Playing_Technology`, in that order. |
| `RAT` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback. |
| `RAT_A` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback. |
| `L2_Call_Mode_A` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback. |
| `Playing_Technology` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback. |
| `Session_Type` | Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Session_Type` and `Type_Of_Test`, in that order. |
| `Type_Of_Test` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered session-family fallback. |
| `Test_Name` | Imports the source value unchanged. |
| `Test_Result` | Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Call_Status`, `Status`, `Result` and `Test_Result`, in that order. It is never converted into a boolean. |
| `Call_Status` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean. |
| `Status` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean. |
| `Result` | Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean. |
| `Event_Start_Time` | Uses the first available call, test or data start field and stores valid timestamps as `YYYY-MM-DD HH:MM:SS.ffffff`. |
| `Event_End_Time` | Uses the first available call, test or data end field and stores valid timestamps in the same ISO format. |
| `Hour_Bucket` | Extracts the hour number from `Event_Start_Time`. |
| `Day_Bucket` | Extracts the day-of-month number from `Event_Start_Time`. |

### Derived Analysis Fields

The following ingestion fields are part of the current analytics model. They provide common names across CDR formats and remain available to filters, chart definitions and workspace Auto-calculated Fields:

| Field | Materialisation rule |
| --- | --- |
| `Direction` | First available `Direction_A`, `Direction` or `Call_Direction`. |
| `Disturbed` | True when `Disturbed_Call` is `Yes`. |
| `Impaired` | True when `Impaired_Call` is `Yes`. |
| `Dropped` | True when status contains `drop` or `Dropped_in_first_70s` is `Yes`. |
| `Unsustainable_Call` | True when `Unsustainable_Call` is `Yes`; otherwise false. |
| `Success` | True for normalized status `completed`, `success`, `ok` or `passed`. |
| `Failure` | True when status is present and `Success` is false. |
| `Setup_Time_Seconds` | First available `Call_Setup_Time`, `Transfer_Access_Duration`, `http_Browser_Access_Duration` or `VideoStream_Time_To_Start_Buffering`, converted to a number. |
| `Duration_Seconds` | First available `Call_Duration`, `Test_Duration`, `Data_Test_Duration`, `Transfer_Duration` or `VideoStream_Video_Stream_Duration`, converted to a number. |
| `Quality_Score` | First available numeric `POLQA_LQ_Avg`, `LQ` or `Mean_Data_Rate`. |
| `Throughput_Mbps` | First available numeric `Mean_Data_Rate`, `TCP_Throughput` or `Data_Throughput`. |
| `Latency_Ms` | First available numeric `Receive_Delay`, `TCP_RTT_Service_Access_Delay` or `DNS_Service_Access_Delay`. |
| `Packet_Loss_Pct` | Row mean of the available `RTP_Packet_Loss_A`, `RTP_Packet_Loss_B` and `Packet_Loss_Score` values. |
| `Jitter_Ms` | Row mean of the available `RTP_Jitter_Avg_A` and `RTP_Jitter_Avg_B` values. |
| `Handovers` | Item count from the first available `Handovers_Info`, `Handovers_Info_A` or `Playing_Handovers`. |
| `Technology_Primary` | First available `RAT`, `RAT_A`, `L2_Call_Mode_A` or `Playing_Technology`. |
| `Technology_Secondary` | First available `L2_Call_Mode_B`, `RAT_B`, `Recording_Technology` or `RAT_Timeline`. |
| `Attempt_Count` | Integer `1` per row, used to count categorical attempts when no numeric KPI exists. |

Analytics uses the success/failure/call-quality flags and the normalized time, quality, throughput, latency, loss, jitter and handover metrics directly. Reporting (old) also uses these normalized metrics as fallbacks for heterogeneous CDR layouts. `Technology_Primary` drives filters and grouping, `Vendor` drives multivendor comparisons, and `Attempt_Count` supplies a stable row-count metric.

`Technology_Secondary` and `Unsustainable_Call` have fewer built-in consumers but remain addressable by templates, filters and Auto-calculated Fields, so they must not be removed without checking workspace definitions and migrating the model.

Normalization version 13 rematerialises version-11 and version-12 CDR datasets once from their uploaded source so `Operator` values previously replaced by a canonical mapping are restored, including datasets that a Vendor-only update had incorrectly marked as version 12 without reloading their source. Vendor mapping changes no longer advance the dataset normalization version.

Version 13 retains the version-11 cleanup of obsolete `__N` collision columns and the former `Report_Vendor` duplicate without deleting the uploaded source file; genuine duplicate source headers retain their explicit `_Duplicate_N` names.

### Combined CDR Tables

The Datasets panel also lists `CDR-Data (combined)`, `CDR-Voice (combined)` and `CDR-Speech (combined)` when they exist. They contain the ready datasets of that CDR type and can be filtered by the same type selector, previewed with the normal CDR preview and rebuilt with the circular **Recreate** action.

Recreate runs in the background and reports progress through [CDR Tables Updates](#cdr-tables-updates). It rebuilds from every ready source dataset, recovers an empty or inconsistent individual row store from its uploaded source file when available, and verifies that each dataset's contribution and final row count match.

> [!NOTE]
> **Read-only role.** `user-viewer` accounts see the workspace datasets but cannot upload, delete, reprocess, stop, map or clear them, change their NR Mode, CDR Type or Combined choice or recreate combined tables; these controls are hidden and the server rejects them.

### Vendor Mapping

> [!WARNING]
> **Remapping.** Map a CDR again to apply a newer mapping file; it replaces the previous result without a prior Clear. Vendor Comparison requires persisted mapping on every selected CDR.

Vendor mapping is required only for Vendor Comparison. The Vendor comes from one of two sources:

- **Network Inventory**: the VFUK and 3UK Multivendor Mappings and the [Network Inventories](#network-inventories) of any other Operator, by the cells of each sample of their Operator.
- **Vendor Polygons (Geographic Datasets)**: the [Vendor polygons](#vendor-polygons) of each sample's Operator, by its position; every Operator that has polygons.

The Map dialog asks for the source when the workspace has both, and uses the only one otherwise; its Vendor mapping rule follows the chosen source.

#### Supported Mapping Files

- **VFUK** workbooks use a `4G` worksheet with `eNodeB ID`, `Local Cell ID` and `OP/ Vendor`. The importer calculates `GCID` as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied Excel hexadecimal formula. A `5G` worksheet may contain `gNodeB ID`, `Local Cell ID` and the vendor field; its stored `GCID` is `gNodeB ID × 4096 + Local Cell ID`.
- **3UK** files contain `Cid__ECI` (the spelling `CId___ECI` is also accepted) and `Vendor`. The ECI value becomes the mapping `GCID` directly.
- Source headers are resolved without regard to case or spaces, underscores and hyphens. Rows without a valid cell identifier or vendor do not create a mapping entry.

#### Assignment Rule

- The CDR must provide `Operator` and a supported serving-cell field such as `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI`.
- The VFUK file applies to every spelling of Vodafone (Vodafone UK, VF, VFUK, and the names of tests configured in another mode such as Vodafone SA, Vodafone VoNR or VF_SA) and the 3UK file to every spelling of Three: they share the same cells. The mapper resolves the first and last cells recorded in the CDR value. Vodafone UK (`Vodafone_` prefix), 3UK (`3_` prefix) and the other spellings (their own name as prefix, for example `Vodafone VoNR_`) follow the same rule:
  - the same non-empty Vendor at both endpoints returns `<Operator>_<Vendor>`;
  - Ericsson at either endpoint with a different or missing Vendor at the other returns `<Operator>_Ericsson_Mixed`;
  - every other different or missing combination returns `<Operator>_Non-Ericsson_Mixed`.
- A [Network Inventory](#network-inventories) applies the same rule to the cells of its own Operator (every spelling of it in Operator Maps); the VFUK and 3UK mappings take precedence for Vodafone and Three.
- Operators without an inventory (for example O2 and EE without a Network Inventory, or Vodafone and Three without a selected mapping) store `<Operator> - All`. CDRs mapped before this rule keep `Vodafone_Mixed Vendor`, `Vodafone_Other Vendor` or `3_Mixed Vendor` until they are mapped again.
- With **Vendor polygons**, the same rule compares the polygon of the sample's own Operator at its start and at its end position: `Call_Start_Latitude_A`/`Call_Start_Longitude_A` and `Call_End_Latitude_A`/`Call_End_Longitude_A` in Voice CDRs. Data CDRs (`Test_Start_*`) and Speech CDRs (`Recording_*`) only record the start, which is then also the end. A sample outside every polygon of its Operator, or without coordinates, stores `<Operator>_Unknown` in `Operator_Vendor` and `Unknown` in `Vendor`; Operators without polygons store `<Operator> - All`. Vodafone and Three spellings share the polygons of their network, like their cells.
- `Vendor` removes the recognised operator prefix from the mapped `Operator_Vendor`, allowing analytics to count the physical vendors independently of the operator. `Vendor_Operator` is `Operator_Vendor` the other way round (`<Vendor>_<Operator>`, and `<Operator> - All` for operators without a vendor); it is derived when the CDRs are read, so every CDR has it without being mapped again. Every filter that offers both keeps them in sync: selecting values in one selects the same identities in the other. CDRs processed before these names are migrated once when the workspace opens: the former `Vendor` becomes `Operator_Vendor` and the former `Vendor_Only` becomes `Vendor`.

#### During Upload

- Ready VFUK and 3UK mappings appear beside each CDR row.
- The newest ready mapping of each type is proposed.
- Either, both or neither may be selected.
- Every ready Network Inventory that can map Vendors is applied as well, for the CDR samples of its Operator.
- When the workspace (or the upload) has Vendor polygons, **Vendor source** chooses between the **Network Inventory** and **Vendor polygons**, which applies every Vendor polygons dataset; it is proposed when there is no Network Inventory.

#### After Upload

1. Click **Map** on a CDR (or **Map Vendor, Region & Cluster** for several).
2. Select one or more ready CDRs, including CDRs that are already mapped. They are listed in CDR Data, Voice and Speech cards side by side, each with **Select All/None**.
3. Choose the Vendor source when the workspace has both; confirm the VFUK and/or 3UK mapping, or the Vendor polygons to apply (all of them are selected), and optionally the Regions and Clusters mappings.
4. Wait for processing to finish.

Mapping a CDR again replaces its previous mapping; **Clear** is only needed to remove the mappings. **Clear Mappings** and **Reprocess Datasets** use the same wide dialog, with the CDRs in CDR Data, Voice and Speech panels (and Other Datasets for Reprocess) and **Select All/None** in each panel. A mapping left as "No … mapping" keeps its previous result. Re-mapping only Vendor recalculates it on the stored rows, which is much faster than rebuilding the CDR; Region and Cluster mappings rebuild the CDR from its source file. Mapping stores the `<Operator>_<Vendor>` identity in `Operator_Vendor` and the vendor name in `Vendor`; operators without an assigned vendor use `Operator - All`. The mapped value is retained in individual and combined CDRs and their dataset exports. Existing processed CDRs receive the new stored identity when mapped again.

The detailed GCID formulas and first/last-cell resolution rules are documented in [Technical Considerations](technical-considerations.md#multivendor-calculation-and-remapping).

## Dataset Inspection and Enrichment

### Dataset Preview

Preview opens persisted rows in a separate view. Regions, Clusters and Vendors datasets open a map instead: their polygons, each in its own colour and named on the map and in the legend, over the grey outline of their countries. The mouse wheel zooms, dragging pans and a double click shows every polygon again.

- Default page size is 100 rows and navigation runs against the complete persisted table.
- A searchable Workspace Dataset selector changes the active dataset. Column-name and label selectors can hide fields without filtering rows.
- Every column menu loads its complete distinct-value list and supports simultaneous Excel-style filters. **Clear N Filters** removes all active value filters.
- Preview order is origin fields, main CDR fields, Auto-calculated Fields, remaining derived fields and then source CDR fields.
- `CDR-Main` identifies source CDR fields used most often by filters and charts. `Derived` identifies normalized ingestion fields, `Auto-calculated` identifies workspace-defined rules, and `Analysis-derived` identifies the remaining shared analytical calculations. `CDR-Data`, `CDR-Voice` or `CDR-Speech` identifies other source fields from that CDR type. Each label and field family has its own colour.
- `PINNED` marks origin, Main, Derived and Auto-calculated fields that remain available across dataset views. `UN_PINNED` marks source-only fields that are present only when supplied by the selected dataset.
- Hover over a `Derived`, `Auto-calculated` or `Analysis-derived` badge to see a formatted tooltip with the field's calculation rule. Select the badge to open the complete rule in a floating details panel.
- Use **Filter Labels** to select one or more labels and show only their columns. **All Labels** restores every column category; this column display filter does not change the dataset rows.
- Mapping previews highlight `GCID` and vendor fields. Their vendor selector uses the vendor alone; inventories keep their source columns and derive it from mapped Vendor values and workspace operator aliases. Preview column filters offer **Operator_Vendor** and **Vendor**. Vendor choices list real vendors first, then Mixed, Other and All groups, then operator-only identities labelled **Operator - All**. The derived column is included with dataset rows in applicable workspace transfers and backups.

### Smart Orchestrator Logs

> [!NOTE]
> **Reserved input type.** Smart Orchestrator Logs is listed for future compatibility; parsing and analysis are not yet supported.

Smart Orchestrator Logs is reserved in the input-type catalogue so existing workspaces and future imports can identify it. Its parsing, normalized schema, Preview rules and analysis workflows are not yet supported; do not use it as a production ingestion type until that processor is implemented.

### Auto-calculated Fields

The **Auto-calculated Fields** panel follows Datasets in Workspace. Fields define a name, optional fallback and ordered rules, and select the applicable CDR types through **Available for**. Source fields are delimited by brackets and alternative aliases use the readable `[Field A] OR [Field B]` form; legacy `Field A|Field B` and unbracketed definitions remain accepted and are normalized when opened.

Typing `[` in either **Default source fields** or **Rules** opens the field catalogue for every selected CDR type, filtered by the prefix entered after the bracket. Rule matching is case-insensitive. The Rules editor accepts either one `condition => result` rule per line or a Tableau-style `IF / THEN / ELSEIF / ELSE / END` expression.

Expressions may be nested, use bracketed source fields such as `[Mean Data Rate]`, quote text values with single or double quotes and join conditions with `AND`. Branches retain normal decision-tree semantics: after an outer `IF` matches, later outer `ELSEIF` branches are not evaluated even when a nested block produces no result.

Use **Apply** in the field editor to keep an edit in the manager's memory, or **Discard** to abandon it and return to the field list. The up/down controls at the start of each row change the field order in memory.

The main **Save** action persists all applied changes without rebuilding CDR tables; **Save & Materialize** persists them and starts the background materialization job. After either operation succeeds, the manager closes. Both actions remain disabled until a field is added, edited, reordered, duplicated or deleted.

Importing JSON or pressing **Re-materialize All Fields**, next to **Edit** and **Export**, also creates a background materialization job; the button is disabled while any CDR table update runs. Workspace remains usable while it runs. The **CDR Tables Updates** card shows one bar per real active task, advances within each table batch and identifies the current table, phase and completed row operations instead of remaining at zero until an entire table finishes.

Fields are applied only to their selected CDR types. The job retains preview-filter fields, fields referenced by rules and the resulting Auto-calculated Fields in the applicable combined table. It removes stale fields from CDR types to which they no longer apply.

## Troubleshooting

- Dataset not offered in Reporting: confirm its assigned type and **Processed** status.
- Dashboard button missing: only ready Data, Voice and Speech CDRs are eligible.
- Vendor Comparison disabled: every selected CDR must have mapping applied.
- Expected campaign missing: inspect the resolved `Campaign` field in Preview.
- Expected city missing: check both the source geographic columns and the normalised field used by the template.
