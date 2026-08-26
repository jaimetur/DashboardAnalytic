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

## Slide catalogue and chart contract

The renderer follows the visual grammar of the supplied template for every automated KPI slide: 100% stacked columns for success/quality splits, stacked count bars for failures, CDF plus average columns for continuous KPIs, paired CDF panels where the template compares two KPIs, and band/radio-quality scatter plots on the dedicated SA Vodafone analysis. Operator colours remain consistent with the template: 3UK orange, EE blue, VFUK red and O2 purple. `Campaign` (or the processed `period` fallback) is the benchmark/category dimension; a multivendor run replaces the operator series with the calculated operator-vendor series.

The technology condition below is always applied before the slide-level filters: NSA contains an ENDC spelling in `RAT`, `RAT_A` or `Sample_RAT_A`; SA contains `NR` in the same fields.

### NSA template

| Slide | Template chart | CDR source and KPI | Additional filters / grouping |
| --- | --- | --- | --- |
| 1 | Cover | None | Preserved template slide. |
| 2 | Executive summary table | None | Preserved for analyst content. |
| 3 | Scoring visual | None | Scoring is not automated. |
| 4 | Score breakdown table | None | Scoring is not automated. |
| 5 | Vodafone gap analysis | None | Scoring/gap analysis is not automated. |
| 6 | Three gap analysis | None | Scoring/gap analysis is not automated. |
| 7 | Section divider | None | Preserved template slide. |
| 8 | 100% stacked completed/dropped/failed columns | CDR-Voice: `Call_Status` | `Session_Type` VoLTE, MultiRAB and WhatsApp; operator × campaign. |
| 9 | Stacked failure-count bars | CDR-Voice: failed/dropped `Call_Status` | VoLTE, MultiRAB and WhatsApp; operator × session/test. |
| 10 | 100% stacked success/failure columns | CDR-Data: `Test_Result` | HTTP/Browsing/Video/YouTube tests; operator × campaign. |
| 11 | 100% stacked FDFS result columns | CDR-Data: `Test_Result` | `Test_Name` containing FDFS; transfer type/direction and operator × campaign. |
| 12 | POLQA CDF with average-MOS columns | CDR-Voice: `POLQA_LQ_Avg` | VoLTE and MultiRAB; operator × campaign. |
| 13 | WhatsApp LQ CDF with average columns | CDR-Speech: `LQ` | WhatsApp sessions; operator × campaign. |
| 14 | Two 100% stacked low-quality charts | CDR-Speech: WhatsApp `LQ`; CDR-Voice: VoLTE `POLQA_LQ_Avg` | `< 1.6` versus `≥ 1.6`; operator × campaign. |
| 15 | CST CDF with average call-setup columns | CDR-Voice: `Call_Setup_Time` | VoLTE/MultiRAB; operator × campaign. |
| 16 | FDTT DL CDF with low-rate throughput distribution | CDR-Data: `FDTT_Sustainable_MDR` | FDTT and DL direction; operator × campaign; low-rate bands are the summary dimension. |
| 17 | FDTT UL CDF with low-rate throughput distribution | CDR-Data: `FDTT_Sustainable_MDR` | FDTT and UL direction; operator × campaign; low-rate bands are the summary dimension. |
| 18 | FDFS DL throughput and transfer-time CDFs with summaries | CDR-Data: `Mean_Data_Rate`, `Data_Test_Duration` | FDFS and DL direction; operator × campaign. |
| 19 | FDFS UL throughput and transfer-time CDFs with summaries | CDR-Data: `Mean_Data_Rate`, `Data_Test_Duration` | FDFS and UL direction; operator × campaign. |
| 20 | Interactivity RTT and packet-error CDFs with summaries | CDR-Data: `Interactivity_RTT_Median`, `Interactivity_Packet_Error_Ratio` | Interactivity tests; operator × campaign. |
| 21 | Browsing time-to-1MB CDF with average summary | CDR-Data: `http_Browser_1MB_Reached_Duration` | Browsing/HTTP tests; operator × campaign. |
| 22 | Conclusions table | None | Preserved for analyst content. |

### SA template

| Slide | Template chart | CDR source and KPI | Additional filters / grouping |
| --- | --- | --- | --- |
| 1 | Cover | None | Preserved template slide. |
| 2 | Agenda | None | Preserved template slide. |
| 3 | Actions tracker | None | Preserved template slide. |
| 4 | Section divider | None | Preserved template slide. |
| 5 | Best-network scoring | None | Scoring is not automated. |
| 6 | Most-reliable scoring | None | Scoring is not automated. |
| 7 | Delta scoring table | None | Scoring is not automated. |
| 8 | London best-network scoring | None | Scoring is not automated. |
| 9 | London reliable-network scoring | None | Scoring is not automated. |
| 10 | London delta scoring table | None | Scoring is not automated. |
| 11 | Voice/speech section divider | None | Preserved template slide. |
| 12 | Stacked voice failure-count bars | CDR-Voice: failed/dropped `Call_Status` | Classic call, MultiRAB and WhatsApp session/test families; operator × campaign. |
| 13 | Vodafone stacked failure-count bars | CDR-Voice: failed/dropped `Call_Status` | Same as slide 12, restricted to Vodafone UK. |
| 14 | 100% stacked completed/dropped/failed columns | CDR-Voice: `Call_Status` | Call, MultiRAB and WhatsApp; operator × campaign. |
| 15 | 100% stacked low-LQ columns | CDR-Speech: `LQ` | `< 1.6` versus `≥ 1.6`; operator × campaign. |
| 16 | Vodafone WhatsApp low-quality visual: band split and radio-quality scatter plots | CDR-Speech: `LQ` against `Playing_RSRP_NR_Avg`/`NR_RSRP_Avg` | Vodafone UK WhatsApp SA samples; `< 1.6` quality state, NR-band/radio-strength dimensions. |
| 17 | Three UK WhatsApp low-quality rate plus POLQA CDF | CDR-Speech: `LQ` | Three UK WhatsApp samples; `< 1.6` versus `≥ 1.6`, operator/campaign grouping. |
| 18 | POLQA AVG MOS CDFs and average-MOS columns | CDR-Voice: `POLQA_LQ_Avg` | Classic/MultiRAB and WhatsApp call families; operator × campaign. |
| 19 | London POLQA AVG MOS CDFs and average-MOS columns | CDR-Voice: `POLQA_LQ_Avg` | Same call families, restricted to a location field matching London; operator × campaign. |
| 20 | Data section divider | None | Preserved template slide. |
| 21 | 100% stacked FDFS success ratio | CDR-Data: `Test_Result` | FDFS DL and UL; operator × campaign. |
| 22 | FDFS DL throughput CDF with transfer summary | CDR-Data: `Mean_Data_Rate` | FDFS, DL; operator × campaign. |
| 23 | FDFS UL throughput CDF with transfer summary | CDR-Data: `Mean_Data_Rate` | FDFS, UL; operator × campaign. |
| 24 | FDTT throughput CDF with low-rate split | CDR-Data: `FDTT_Sustainable_MDR` | FDTT DL/UL; operator × campaign. |
| 25 | Interactivity CDF with RTT summary | CDR-Data: `Interactivity_RTT_Median` | Interactivity tests; operator × campaign. |
| 26 | Browsing CDF with time-to-1MB average | CDR-Data: `http_Browser_1MB_Reached_Duration` | Browsing/HTTP tests; operator × campaign. |
| 27 | Conclusions | None | Preserved for analyst content. |
| 28 | Closing slide | None | Preserved template slide. |
