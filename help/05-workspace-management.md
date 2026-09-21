# Workspace Management

Workspace Management is the first operational module. It controls isolated workspaces, their storage, dataset ingestion, processing queue and vendor mapping workflows.

## Workspace Lifecycle

- Create, open, close, rename, duplicate and delete workspaces.
- Review workspace size and access.
- Keep databases, uploaded files and generated output isolated.
- Open a workspace before using Dashboard, Reporting or Chart Builder.

## Data Ingestion

Workspace accepts `CSV`, `XLS`, `XLSX` and `XLSM`. Only successfully processed datasets can be used by Dashboard, Chart Builder or Reporting.

### Supported Input Types

- CDR-Data
- CDR-Voice
- CDR-Speech
- Multivendor Mapping — VFUK
- Multivendor Mapping — 3UK
- Smart Orchestrator Logs — listed for forward compatibility; ingestion and analysis are not yet implemented.
- Other

### Upload Workflow

1. Open the target workspace.
2. Select one or more files in **Data Ingestion**.
3. Review the proposed type for every file.
4. For CDRs, optionally choose ready VFUK/3UK mappings.
5. Confirm the batch.
6. Follow every item in **Queue and Status**.
7. Continue only when the status is **Processed**.

Classification is proposed from filenames but remains reviewable. Examples:

- `NetCheck_CDR_Data_2026_Q2.xlsx` → CDR-Data
- `NetCheck_CDR_Voice_2026_Q2.xlsx` → CDR-Voice
- `VFUK_Multivendor_Mapping.xlsx` → VFUK mapping

### Background Processing

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

### Combined Table Recreation

The **Datasets** table shows comma-grouped Rows and Columns for each individual and combined dataset, and separates generated, read-only query sources from uploaded datasets with a dedicated heading, description and repeated column header. Combined tables cannot be imported separately: CDR processing creates them from all ready individual CDRs of the same type. The circular **Recreate combined table** action checks every ready individual CDR of that type in the background before rebuilding the combined table. If an individual table uses an older normalization version, the job migrates it from its original source file first; one recreation each for Data, Voice and Speech therefore upgrades both their individual and combined tables. Its live task detail identifies the individual table being migrated. Opening a combined preview performs the same compatibility check, and its Loading Dataset panel explains when all individual tables of that CDR type may need migration. The shared **Materialization status** card appears below the complete Datasets table because its progress covers both individual and combined CDR tables; when several materializations are active or queued, it presents each task with its own label, message and progress bar. Successful completion refreshes the table's counts, status, progress and Updated values in place without reloading the Workspace page.

### Fixed CDR Fields

The processor materialises every fixed field even when all its values are empty. Dataset Preview places them after `Source_File`, `Source_Sheet` and `Dataset_Kind` in the order shown below. Each field follows its own rule:

- **`Operator`** — Imports and preserves the source `Operator`, `Operator_A`, `Home_Operator_A` or `Home_Operator` value. Workspace Operator Mappings affect chart presentation and chart-template filters only; Dataset Preview, Dataset Analysis selectors and combined CDR tables remain source-faithful.
- **`Subscriber`** — Keeps the source `Subscriber` or legacy `Suscriber` value. If the complete field is absent or empty, it copies `Operator`.
- **`Vendor`** — Stores `Operator_Vendor` for operators resolved through a multivendor cell mapping and the canonical `Operator` for all other operators. This is the single official comparison field used by filters, legends and reports.
- **`Vendor_Only`** — Derives from `Vendor` by removing a recognised operator prefix, including configured Vodafone/VF, Three/3/H3G, O2 and EE aliases.
- **`Campaign`** — Keeps the exact source value. Comparisons and chart labels recognise reordered country, year, quarter and SA/NSA tokens and can present `YYYY-Qn`, `YYYY-Qn_SA` or `YYYY-Qn_NSA`. A mode-free equality filter does not merge SA and NSA records.
- **`Benchmark`** — Keeps the source value. If the complete source column is absent or empty, it copies `Campaign`.
- **`Campaign_Year`** — Extracts the first four-digit year from `Campaign`, using `Benchmark` as the per-row fallback.
- **`Campaign_Quarter`** — Extracts `Q1`, `Q2`, `Q3` or `Q4` from `Campaign`, using `Benchmark` as the per-row fallback.
- **`Period`** — Joins `Campaign_Year` and `Campaign_Quarter` as `YYYY-Qn`.
- **`Market`** — Recognises a delimited ISO country code or English country name in `Campaign`, then in `Benchmark`, and stores the two-letter code.
- **`Region`** — Keeps the source value and remains empty when the source field is absent.
- **`Zone`** — Keeps the source value; otherwise copies `G_Level_3`; otherwise remains empty.
- **`City`** — Keeps the source value; otherwise copies `G_Level_4`; otherwise remains empty.
- **`Technology`** — Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Technology`, `RAT`, `RAT_A`, `L2_Call_Mode_A` and `Playing_Technology`, in that order.
- **`RAT`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback.
- **`RAT_A`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback.
- **`L2_Call_Mode_A`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback.
- **`Playing_Technology`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered technology-family fallback.
- **`Session_Type`** — Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Session_Type` and `Type_Of_Test`, in that order.
- **`Type_Of_Test`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered session-family fallback.
- **`Test_Name`** — Imports the source value unchanged.
- **`Test_Result`** — Keeps its source values. If its complete column is absent or empty, it copies the first populated field from `Call_Status`, `Status`, `Result` and `Test_Result`, in that order. It is never converted into a boolean.
- **`Call_Status`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean.
- **`Status`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean.
- **`Result`** — Keeps its source values. If its complete column is absent or empty, it uses the same ordered result-family fallback. It is never converted into a boolean.
- **`Event_Start_Time`** — Uses the first available call, test or data start field and stores valid timestamps as `YYYY-MM-DD HH:MM:SS.ffffff`.
- **`Event_End_Time`** — Uses the first available call, test or data end field and stores valid timestamps in the same ISO format.
- **`Hour_Bucket`** — Extracts the hour number from `Event_Start_Time`.
- **`Day_Bucket`** — Extracts the day-of-month number from `Event_Start_Time`.

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

Analytics uses the success/failure/call-quality flags and the normalized time, quality, throughput, latency, loss, jitter and handover metrics directly. E2E Reporting also uses these normalized metrics as fallbacks for heterogeneous CDR layouts. `Technology_Primary` drives filters and grouping, `Vendor` drives multivendor comparisons, and `Attempt_Count` supplies a stable row-count metric. `Technology_Secondary` and `Unsustainable_Call` have fewer built-in consumers but remain addressable by templates, filters and Auto-calculated Fields, so they must not be removed without checking workspace definitions and migrating the model.

Normalization version 13 rematerialises version-11 and version-12 CDR datasets once from their uploaded source so `Operator` values previously replaced by a canonical mapping are restored, including datasets that a Vendor-only update had incorrectly marked as version 12 without reloading their source. Vendor mapping changes no longer advance the dataset normalization version. Version 13 retains the version-11 cleanup of obsolete `__N` collision columns and the former `Report_Vendor` duplicate without deleting the uploaded source file; genuine duplicate source headers retain their explicit `_Duplicate_N` names.

### Combined CDR Tables

The Datasets panel also lists `CDR-Data (combined)`, `CDR-Voice (combined)` and `CDR-Speech (combined)` when they exist. They contain the ready datasets of that CDR type and can be filtered by the same type selector, previewed with the normal CDR preview and rebuilt with the circular **Recreate** action.

Recreate runs in the background and reports progress through Materialization status. It rebuilds from every ready source dataset, recovers an empty or inconsistent individual row store from its uploaded source file when available, and verifies that each dataset's contribution and final row count match.

### Vendor Mapping

Vendor mapping is required only for Vendor Comparison.

#### Supported Mapping Files

- **VFUK** workbooks use a `4G` worksheet with `eNodeB ID`, `Local Cell ID` and `OP/ Vendor`. The importer calculates `GCID` as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied Excel hexadecimal formula. A `5G` worksheet may contain `gNodeB ID`, `Local Cell ID` and the vendor field; its stored `GCID` is `gNodeB ID × 4096 + Local Cell ID`.
- **3UK** files contain `Cid__ECI` (the spelling `CId___ECI` is also accepted) and `Vendor`. The ECI value becomes the mapping `GCID` directly.
- Source headers are resolved without regard to case or spaces, underscores and hyphens. Rows without a valid cell identifier or vendor do not create a mapping entry.

#### Assignment Rule

- The CDR must provide `Operator` and a supported serving-cell field such as `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI`.
- The mapper resolves the first and last cells recorded in the CDR value. When both resolve to the same non-empty vendor, `Vendor` becomes `Operator_Vendor` for Vodafone UK or 3UK.
- For Vodafone UK, an Ericsson/non-Ericsson conflict becomes `Vodafone_Mixed Vendor`; other unresolved combinations become `Vodafone_Other Vendor`. For 3UK, different or unresolved endpoints become `3_Mixed Vendor`. Operators without a multivendor mapping use their canonical `Operator`.
- `Vendor_Only` removes the recognised operator prefix from a mapped `Vendor`, allowing analytics to count the physical vendors independently of the operator.

#### During Upload

- Ready VFUK and 3UK mappings appear beside each CDR row.
- The newest ready mapping of each type is proposed.
- Either, both or neither may be selected.

#### After Upload

1. Click **Map Vendors**.
2. Select one or more ready CDRs.
3. Confirm the VFUK and/or 3UK mapping.
4. Wait for processing to finish.

Use **Clear Vendors** before remapping with a newer file.

The detailed GCID formulas and first/last-cell resolution rules are documented in [Technical Considerations](02-technical-considerations.md#multivendor-calculation-and-remapping).

## Dataset Inspection and Enrichment

### Dataset Preview

Preview opens persisted rows in a separate view.

- Default page size is 100 rows and navigation runs against the complete persisted table.
- A searchable Workspace Dataset selector changes the active dataset. Column-name and label selectors can hide fields without filtering rows.
- Every column menu loads its complete distinct-value list and supports simultaneous Excel-style filters. **Clear N Filters** removes all active value filters.
- Preview order is origin fields, main CDR fields, Auto-calculated Fields, remaining derived fields and then source CDR fields.
- `CDR-Main` identifies source CDR fields used most often by filters and charts. `Derived` identifies normalized ingestion fields, `Auto-calculated` identifies workspace-defined rules, and `Analysis-derived` identifies the remaining shared analytical calculations. `CDR-Data`, `CDR-Voice` or `CDR-Speech` identifies other source fields from that CDR type. Each label and field family has its own colour.
- `PINNED` marks origin, Main, Derived and Auto-calculated fields that remain available across dataset views. `UN_PINNED` marks source-only fields that are present only when supplied by the selected dataset.
- Hover over a `Derived`, `Auto-calculated` or `Analysis-derived` badge to see a formatted tooltip with the field's calculation rule. Select the badge to open the complete rule in a floating details panel.
- Use **Filter Labels** to select one or more labels and show only their columns. **All Labels** restores every column category; this column display filter does not change the dataset rows.
- Mapping previews highlight `GCID` and vendor fields.

### Smart Orchestrator Logs

Smart Orchestrator Logs is reserved in the input-type catalogue so existing workspaces and future imports can identify it. Its parsing, normalized schema, Preview rules and analysis workflows are not yet supported; do not use it as a production ingestion type until that processor is implemented.

### Auto-calculated Fields

The **Auto-calculated Fields** panel follows Datasets in Workspace. Fields define a name, optional fallback and ordered rules, and select the applicable CDR types through **Available for**. Source fields are delimited by brackets and alternative aliases use the readable `[Field A] OR [Field B]` form; legacy `Field A|Field B` and unbracketed definitions remain accepted and are normalized when opened. Typing `[` in either **Default source fields** or **Rules** opens the field catalogue for every selected CDR type, filtered by the prefix entered after the bracket. Rule matching is case-insensitive. The Rules editor accepts either one `condition => result` rule per line or a Tableau-style `IF / THEN / ELSEIF / ELSE / END` expression. Expressions may be nested, use bracketed source fields such as `[Mean Data Rate]`, quote text values with single or double quotes and join conditions with `AND`. Branches retain normal decision-tree semantics: after an outer `IF` matches, later outer `ELSEIF` branches are not evaluated even when a nested block produces no result.

Use **Apply** in the field editor to keep an edit in the manager's memory, or **Discard** to abandon it and return to the field list. The up/down controls at the start of each row change the field order in memory. The main **Save** action persists all applied changes without rebuilding CDR tables; **Save & Materialize** persists them and starts the background materialization job. After either operation succeeds, the manager closes. Both actions remain disabled until a field is added, edited, reordered, duplicated or deleted. Importing JSON or pressing the green rematerialization action in the **Materialization status** panel also creates a background materialization job. Workspace remains usable while it runs. The panel shows one bar per real active task, advances within each table batch and identifies the current table, phase and completed row operations instead of remaining at zero until an entire table finishes.

Fields are applied only to their selected CDR types. The job retains preview-filter fields, fields referenced by rules and the resulting Auto-calculated Fields in the applicable combined table. It removes stale fields from CDR types to which they no longer apply.

## Troubleshooting

- Dataset not offered in Reporting: confirm its assigned type and **Processed** status.
- Dashboard button missing: only ready Data, Voice and Speech CDRs are eligible.
- Vendor Comparison disabled: every selected CDR must have mapping applied.
- Expected campaign missing: inspect the resolved `Campaign` field in Preview.
- Expected city missing: check both the source geographic columns and the normalised field used by the template.
