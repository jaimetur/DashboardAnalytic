# PowerPoint reporting

Dashboard Analytic supports a generic dashboard export and a template-backed NetCheck CDR report. The latter is available from **E2E Bench Reporting → NetCheck CDR Reports**.

## Before generating a NetCheck report

Upload and process the required files in Workspace first:

- one `CDR-Data` workbook;
- one `CDR-Voice` workbook; and
- one `CDR-Speech` workbook.

For a Multivendor report, also process one **VFUK Vodafone UK** mapping and one **3UK Three UK** mapping. The report page lists each mapping only in its corresponding operator selector, so an input that has not finished processing or has the wrong mapping type will not be selectable. The mapping controls remain hidden for a Single-vendor run.

## Report options

Choose the technology according to the required session scope:

| Technology | CDR session filter |
| --- | --- |
| **NSA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `ENDC`. |
| **SA** | The same field contains `NR`. |

Then choose a report scope:

- **Single-vendor** generates the operator analysis without requesting mappings.
- **Multivendor** reveals mandatory, separate Vodafone and Three mapping selectors and creates series by operator-vendor combination where applicable.

## Vendor calculation

For Vodafone and Three, the report derives vendor from the first and last value available in CDR `Cell_ID_A`, `Cell_IDs_A` or `Cell_ID` and the corresponding mapping. During 3UK processing, Workspace materialises `GCID` from the same value as `Cid__ECI` (or `CId___ECI`). During VFUK processing, it materialises the 4G GCID as `eNodeB ID × 256 + Local Cell ID`; this is equivalent to `HEX2DEC(DEC2HEX(eNodeB ID, 5) & DEC2HEX(Local Cell ID, 2))` in Excel. It also materialises the existing 5G convention, `gNodeB ID × 4096 + Local Cell ID`, for inspection in the mapping preview. The report's Vodafone lookup remains based on the agreed 4G mapping formula. The agreed business formula is authoritative: matching mapped endpoints yield that vendor; Vodafone explicitly distinguishes Ericsson-related mixed cases, other mixed cases and missing endpoints; Three uses a mixed-vendor result for non-matching endpoints. O2 and EE remain represented as the operator.

## Generated presentation

The report uses the NSA or SA template under `assets/templates/` (or the directory configured through `APP_REPORTING_TEMPLATE_DIR`). It preserves the provided presentation structure, removes inherited example chart graphics in the automated chart areas and inserts new charts computed from the processed CDR rows. Commentary areas are deliberately blank for analyst input. Scoring and GAP-analysis slides remain present but are not populated automatically at this stage.

After generation, the PPTX downloads through the browser and the generation dialog closes. If the report contains no valid samples, re-check the selected technology, operator sheets and CDR inputs; the message indicates that the selected persisted rows did not match the relevant KPI and technology filter. For NSA, validate that the relevant RAT field actually contains an ENDC variant; for SA, validate the expected `NR` values.
