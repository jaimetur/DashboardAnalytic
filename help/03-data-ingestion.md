# Data ingestion

The Workspace accepts CSV, XLSX, XLS and XLSM files. Uploaded data, metadata and normalised rows are stored in the open workspace only. Its files and SQLite database live under `data/workspaces/<Workspace Name>/`. Only processed datasets can be analysed or used in reports.

## Standard workflow

1. Sign in and select a workspace, or create one from **Workspaces Management**.
2. Open the workspace and upload the source file.
3. Confirm the detected type and source name; for a batch, review every proposed type independently.
4. Wait until its status is **Processed**.
5. Open E2E Dashboard or E2E PowerPoint Reporting and select the processed dataset.

If a status shows an error, correct the source and upload it again. Do not create a report from a failed or incomplete ingestion.

Processing continues on the server after sign-out or after the workspace is closed. Each queued import retains the database of the workspace that received it, so reopening that workspace later shows the updated status. Stopping an import still requires the explicit **Stop** action.

## Queue, preview and dashboard

The **Data Processing** queue starts with **All Types** selected and can be narrowed to any supported input type. After successful processing, select **Preview** to inspect a read-only sample of 100 rows by default (or a customised value) from the persisted dataset. The preview opens in a new tab and supports text filters plus Excel-style multi-value menus on column headers. CDR previews also provide multi-select Operator, Vendor, RAT/RAT_A, Session Type and Call Status controls, with all available values selected by default. For CDR Data, Voice and Speech inputs, **Show Dashboard** opens KPI analysis directly; mappings and Smart Orchestrator Logs remain available for their dedicated workflows without being sent to the CDR dashboard.

## Excel workbooks

For Excel inputs, each readable worksheet is inspected. The application records worksheet names, row and column counts and a compact profile that can be used by the analysis layer. CDR workbooks commonly contain an operator worksheet; the reporting pipeline reads these sheets individually rather than assuming one fixed sheet layout.

## NetCheck CDR inputs

A NetCheck report requires three separately processed CDR workbooks:

- **Data**;
- **Voice**;
- **Speech**.

When files are selected, Workspace derives a proposed type from each filename and preselects it. Names containing `Data`, `Voice` or `Speech` are proposed as the corresponding CDR domain; names containing `VFUK`/`Vodafone` or `3UK`/`Three` are proposed as the corresponding mapping; Smart Orchestrator/log names are proposed as log inputs. For multiple files, it presents a confirmation panel so every proposed classification can be reviewed individually. If a row is a CDR and ready mapping files are already in Workspace, two additional selectors appear for VFUK and 3UK. Each selector proposes the most recently uploaded ready mapping of its type and includes **No Map Vendor Column**. Select either, both or neither; only the selected operator mappings are applied during that CDR's processing. The selected type and mapping choices are persisted before processing, so the reporting form can offer the appropriate selector. NSA sessions are identified from `RAT`, `RAT_A` or `Sample_RAT_A` values containing an ENDC spelling; SA sessions use values containing `NR`. The generator validates the selected combination before starting.

## Smart Orchestrator Logs

Smart Orchestrator Log files can already be uploaded, classified and retained in Workspace. They are not yet analysed by a dedicated reporting module, but keeping their type explicit prevents them from being confused with CDR or mapping sources and prepares them for the future Smart Orchestrator Logs Reports workflow.

## Multivendor mapping inputs

Multivendor mapping uses processed mapping files: **VFUK** for Vodafone UK and **3UK** for Three UK. Workspace preselects these types when the filename includes the corresponding identifier; always confirm the proposal. O2 and EE are not mapped as multivendor operators. The CDR **Map Vendors** action lists every ready, unmapped CDR so one or more can be selected in a single operation. It automatically selects the latest ready VFUK and 3UK mapping of each available type, while still allowing either mapping to be set to **No mapping**.

| Source | Required input | How the lookup is built |
| --- | --- | --- |
| CDR Data, Voice or Speech | `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI` | The reporting flow extracts the first and last Global Cell ID available for each session; case and separator variations are accepted. |
| 3UK mapping | `Cid__ECI` (the source variant `CId___ECI` is also accepted) and Vendor | Processing materialises `GCID` as the same value, which is then matched directly to the CDR endpoint GCID. |
| VFUK mapping | `4G` worksheet with `eNodeB ID`, `Local Cell ID` and Vendor; optionally `5G` with `gNodeB ID` and `Local Cell ID` | Processing materialises a `GCID` column for `4G` as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied hexadecimal Excel formula. It also materialises the existing `5G` calculation, `gNodeB ID × 4096 + Local Cell ID`. The mapping preview is limited to these two sheets and provides a selector between them. |

After the mappings are processed, either select them during each CDR import or use **Map Vendors** later on every Data, Voice and Speech CDR that will be used for multivendor analysis. Both paths use the same first/last-Cell-ID rule. The queue dialog lists only ready VFUK/3UK mapping datasets; the import selectors independently support VFUK-only, 3UK-only or both. Mapping writes Vendor only for Vodafone UK and 3UK samples; O2/EE remain operators rather than vendors. When submitted from **Map Vendors**, each selected CDR is queued and displays its ordinary Workspace status and progress bar, so the analyst can keep working while mapping completes. **Clear Vendors** uses the same background queue and supports selecting several mapped CDRs to restore them for a clean remap. Reporting enables Multivendor only after this operation has been completed for every selected CDR.
