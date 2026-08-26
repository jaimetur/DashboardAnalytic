# Data ingestion

The Workspace accepts CSV, XLSX, XLS and XLSM files. Uploaded data is stored with its metadata in SQLite and its tabular contents are normalised under the configured output directory. Only processed datasets can be analysed or used in reports.

## Standard workflow

1. Sign in and open **Workspace**.
2. Upload the source file.
3. Wait until its status is **Processed**.
4. Confirm the detected type and source name; for a batch, review every proposed type independently.
5. Open E2E Bench Dashboard or E2E Bench Reporting and select the processed dataset.

If a status shows an error, correct the source and upload it again. Do not create a report from a failed or incomplete ingestion.

## Queue, preview and dashboard

The **Data Processing** queue starts with **All Types** selected and can be narrowed to any supported input type. After successful processing, select **View** to inspect a read-only sample of up to 100 rows from the persisted dataset. For CDR Data, Voice and Speech inputs, **Show Dashboard** is displayed to open the KPI analysis directly; mappings and Smart Orchestrator Logs remain available for their dedicated workflows without being sent to the CDR dashboard.

## Excel workbooks

For Excel inputs, each readable worksheet is inspected. The application records worksheet names, row and column counts and a compact profile that can be used by the analysis layer. CDR workbooks commonly contain an operator worksheet; the reporting pipeline reads these sheets individually rather than assuming one fixed sheet layout.

## NetCheck CDR inputs

A NetCheck report requires three separately processed CDR workbooks:

- **Data**;
- **Voice**; and
- **Speech**.

When files are selected, Workspace derives a proposed type from each filename and preselects it. Names containing `Data`, `Voice` or `Speech` are proposed as the corresponding CDR domain; names containing `VFUK`/`Vodafone` or `3UK`/`Three` are proposed as the corresponding mapping; Smart Orchestrator/log names are proposed as log inputs. For multiple files, it presents a confirmation panel so every proposed classification can be reviewed individually. The selected type is persisted before processing, so the reporting form can offer the appropriate selector. NSA sessions are identified from `RAT`, `RAT_A` or `Sample_RAT_A` values containing an ENDC spelling; SA sessions use values containing `NR`. The generator validates the selected combination before starting.

## Smart Orchestrator Logs

Smart Orchestrator Log files can already be uploaded, classified and retained in Workspace. They are not yet analysed by a dedicated reporting module, but keeping their type explicit prevents them from being confused with CDR or mapping sources and prepares them for the future Smart Orchestrator Logs Reports workflow.

## Multivendor mapping inputs

Multivendor reporting requires two processed mapping files: **VFUK** for Vodafone UK and **3UK** for Three UK. Workspace preselects these types when the filename includes the corresponding identifier; always confirm the proposal. O2 and EE are not mapped as multivendor operators. The mappings are selected separately so the system can resolve vendors from the first and last Global Cell ID seen in each session.

| Source | Required input | How the lookup is built |
| --- | --- | --- |
| CDR Data, Voice or Speech | `Cell_ID_A`, `Cell_IDs_A` or `Cell_ID` | The reporting flow extracts the first and last Global Cell ID available for each session. |
| 3UK mapping | `Cid__ECI` (the source variant `CId___ECI` is also accepted) and Vendor | Processing materialises `GCID` as the same value, which is then matched directly to the CDR endpoint GCID. |
| VFUK mapping | `4G` worksheet with `eNodeB ID`, `Local Cell ID` and Vendor; optionally `5G` with `gNodeB ID` and `Local Cell ID` | Processing materialises a `GCID` column for `4G` as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied hexadecimal Excel formula. It also materialises the existing `5G` calculation, `gNodeB ID × 4096 + Local Cell ID`. The mapping preview is limited to these two sheets and provides a selector between them. |

Keep the Vendor field populated and verify that the mapping has been processed successfully before opening Reporting. A mapping with an incorrect assigned type will not appear in its Vodafone or Three selector.
