# Workspace Management

Workspace Management is the first operational module. It controls isolated workspaces, their storage, dataset ingestion, processing queue and vendor mapping workflows.

## Workspaces Management

- Create, open, close, rename, duplicate and delete workspaces.
- Review workspace size and access.
- Keep databases, uploaded files and generated output isolated.
- Open a workspace before using Dashboard, Reporting or Chart Builder.

## Data Ingestion

Workspace accepts `CSV`, `XLS`, `XLSX` and `XLSM`. Only successfully processed datasets can be used by Dashboard, Chart Builder or Reporting.

## Supported input types

- CDR-Data
- CDR-Voice
- CDR-Speech
- Multivendor Mapping — VFUK
- Multivendor Mapping — 3UK
- Smart Orchestrator Logs
- Other

## Upload workflow

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

## Background processing

- A queued import retains its target workspace even if the user switches workspace.
- Processing continues after sign-out.
- Stop requests are cooperative.
- Failed or stopped work can be retried.
- Re-uploading the same stored dataset preserves its original upload date.
- Updated time records the latest processing operation.

## Workbook handling

- Readable worksheets are inspected.
- Known summary sheets are ignored.
- Operator/data sheets can be concatenated.
- Source columns are retained with collision-safe names.
- Normalised fields are materialised for consistent analysis.

## Dataset preview

Preview opens persisted rows in a separate view.

- Default page size is 100 rows.
- Search can match rows or columns.
- Column menus provide Excel-style value selection.
- CDR previews add relevant Operator, Vendor, RAT, Call Family and Test Family controls.
- Mapping previews highlight `GCID` and vendor fields.
- Derived columns use a light-grey visual treatment.

## Vendor mapping

Vendor mapping is required only for Vendor Comparison.

### During upload

- Ready VFUK and 3UK mappings appear beside each CDR row.
- The newest ready mapping of each type is proposed.
- Either, both or neither may be selected.

### After upload

1. Click **Map Vendors**.
2. Select one or more ready CDRs.
3. Confirm the VFUK and/or 3UK mapping.
4. Wait for processing to finish.

Use **Clear Vendors** before remapping with a newer file.

The detailed GCID formulas and first/last-cell resolution rules are documented in [Technical Considerations](02-technical-considerations.md#multivendor-calculation-and-remapping).

## Troubleshooting

- Dataset not offered in Reporting: confirm its assigned type and **Processed** status.
- Dashboard button missing: only ready Data, Voice and Speech CDRs are eligible.
- Vendor Comparison disabled: every selected CDR must have mapping applied.
- Expected campaign missing: inspect the resolved `Campaign` field in Preview.
- Expected city missing: check both the source geographic columns and the normalised field used by the template.
