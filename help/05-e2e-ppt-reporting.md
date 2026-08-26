# 5. E2E PowerPoint Reporting

Dashboard Analytic supports a generic dashboard export and a template-backed NetCheck CDR report. The latter is available from **E2E PowerPoint Reporting → NetCheck CDR Reports**.

## Before generating a NetCheck report

Upload and process the required files in Workspace first:

- one `CDR-Data` workbook;
- one `CDR-Voice` workbook;
- one `CDR-Speech` workbook.

For a Multivendor report, also process one **VFUK Vodafone UK** mapping and one **3UK Three UK** mapping. The report page lists each mapping only in its corresponding operator selector, so an input that has not finished processing or has the wrong mapping type will not be selectable. The mapping controls remain hidden for a Single-vendor run.

## Report options

Choose the technology according to the required session scope:

| Technology | CDR session filter |
| --- | --- |
| **NSA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `ENDC`. |
| **SA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `NR`. |

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

The editable CSV exports use the same rows and column order as these tables: [NSA](nsa-slide-catalogue.csv) and [SA](sa-slide-catalogue.csv).

### NSA template

| Slide | Template chart | CDR source | KPI | Chart type | Filters | Grouping |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2025 Q4 Net check UK NSA CDR analysis | — | — | Preserved cover | — | — |
| 2 | Executive Summary | — | — | Preserved summary | — | — |
| 3 | Netcheck Q4 scoring “Best network”. Drive city | — | — | Not automated | — | — |
| 4 | Score breakdown | — | — | Not automated | — | — |
| 5 | KPIs prioritization: gap Vodafone vs EE | — | — | Not automated | — | — |
| 6 | KPIs prioritization: gap Three vs EE | — | — | Not automated | — | — |
| 7 | 7 cities analysis | — | — | Preserved section divider | — | — |
| 8 | Completed Call Ratio | CDR-Voice | `Call_Status` | 100% stacked column | `Session_Type`: VoLTE, MultiRAB, WhatsApp | Call family × Operator × Campaign |
| 9 | Voice failures per Q/city | CDR-Voice | `Call_Status` | Stacked horizontal count bar | Failed/Dropped; VoLTE, MultiRAB, WhatsApp | Call family × City × Operator × Campaign |
| 10 | Data failure | CDR-Data | `Test_Result` | 100% stacked column | HTTP, Browsing, Video and YouTube tests | Test family × Operator × Campaign |
| 11 | Data failures - FDFS test | CDR-Data | `Test_Result` | 100% stacked column | `Test_Name` contains FDFS | Test name × Direction × Operator × Campaign |
| 12 | POLQA AVG MOS (Multirab&volte) | CDR-Voice | `POLQA_LQ_Avg` | CDF line | `Session_Type`: VoLTE or MultiRAB | Operator × Campaign |
| 12 | POLQA AVG MOS (Multirab&volte) | CDR-Voice | `POLQA_LQ_Avg` | Average-MOS column | `Session_Type`: VoLTE or MultiRAB | Operator × Campaign |
| 13 | POLQA AVG MOS (WhatsApp) | CDR-Speech | `LQ` | CDF line | `Session_Type` contains WhatsApp | Operator × Campaign |
| 13 | POLQA AVG MOS (WhatsApp) | CDR-Speech | `LQ` | Average-MOS column | `Session_Type` contains WhatsApp | Operator × Campaign |
| 14 | POLQA <1.6 | CDR-Speech | `LQ` | 100% stacked column | WhatsApp; LQ < 1.6 vs ≥ 1.6 | Operator × Campaign |
| 14 | POLQA <1.6 | CDR-Voice | `POLQA_LQ_Avg` | 100% stacked column | VoLTE; POLQA < 1.6 vs ≥ 1.6 | Operator × Campaign |
| 15 | CST | CDR-Voice | `Call_Setup_Time` | CDF line | `Session_Type`: VoLTE or MultiRAB | Operator × Campaign |
| 15 | CST | CDR-Voice | `Call_Setup_Time` | Average call-setup-time column | `Session_Type`: VoLTE or MultiRAB | Operator × Campaign |
| 16 | FDTT DL (7s) | CDR-Data | `FDTT_Sustainable_MDR` | CDF line | FDTT; Direction DL | Operator × Campaign |
| 16 | FDTT DL (7s) | CDR-Data | `FDTT_Sustainable_MDR` | Stacked low-rate distribution | FDTT; Direction DL; template rate buckets | Operator × Campaign × Rate bucket |
| 17 | FDTT UL (7s) | CDR-Data | `FDTT_Sustainable_MDR` | CDF line | FDTT; Direction UL | Operator × Campaign |
| 17 | FDTT UL (7s) | CDR-Data | `FDTT_Sustainable_MDR` | Stacked low-rate distribution | FDTT; Direction UL; template rate buckets | Operator × Campaign × Rate bucket |
| 18 | FDFS DL | CDR-Data | `Mean_Data_Rate` | CDF line | FDFS; Direction DL | Operator × Campaign |
| 18 | FDFS DL | CDR-Data | `Data_Test_Duration` | CDF line | FDFS; Direction DL | Operator × Campaign |
| 18 | FDFS DL | CDR-Data | `Data_Test_Duration` | Average transfer-time column | FDFS; Direction DL | Operator × Campaign |
| 19 | FDFS UL | CDR-Data | `Mean_Data_Rate` | CDF line | FDFS; Direction UL | Operator × Campaign |
| 19 | FDFS UL | CDR-Data | `Data_Test_Duration` | CDF line | FDFS; Direction UL | Operator × Campaign |
| 19 | FDFS UL | CDR-Data | `Data_Test_Duration` | Average transfer-time column | FDFS; Direction UL | Operator × Campaign |
| 20 | Interactivity | CDR-Data | `Interactivity_RTT_Median` | CDF line | Interactivity tests | Operator × Campaign |
| 20 | Interactivity | CDR-Data | `Interactivity_RTT_Median` | Median RTT column | Interactivity tests | Operator × Campaign |
| 20 | Interactivity | CDR-Data | `Interactivity_Packet_Error_Ratio` | CDF line | Interactivity tests | Operator × Campaign |
| 20 | Interactivity | CDR-Data | `Interactivity_Packet_Error_Ratio` | Average packet-error-ratio column | Interactivity tests | Operator × Campaign |
| 21 | Browsing | CDR-Data | `http_Browser_1MB_Reached_Duration` | CDF line | Browsing/HTTP tests | Operator × Campaign |
| 21 | Browsing | CDR-Data | `http_Browser_1MB_Reached_Duration` | Average time-to-1MB column | Browsing/HTTP tests | Operator × Campaign |
| 22 | Conclusions | — | — | Preserved conclusions | — | — |

### SA template

| Slide | Template chart | CDR source | KPI | Chart type | Filters | Grouping |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | NPPI Tech Forum VodafoneThree & Ericsson 2026-08-06 | — | — | Preserved cover | — | — |
| 2 | Agenda | — | — | Preserved agenda | — | — |
| 3 | Actions Tracker | — | — | Preserved tracker | — | — |
| 4 | Netcheck CDR Scoring and Gap Analysis 2026 Q2 NSA vs SA Campaign 7 Cities and London | — | — | Preserved section divider | — | — |
| 5 | Netcheck 5G SA Best Network Scoring 7 Cities | — | — | Not automated | — | — |
| 6 | Netcheck 5G SA Most Reliable Network Scoring 7 Cities | — | — | Not automated | — | — |
| 7 | Q2 2026 vs SA Campaign – Delta Scoring 7 Cities | — | — | Not automated | — | — |
| 8 | Netcheck 5G SA Best Network Scoring London | — | — | Not automated | — | — |
| 9 | Netcheck 5G SA Most Reliable Network Scoring London | — | — | Not automated | — | — |
| 10 | Q2 2026 vs SA Campaign – Delta Scoring London | — | — | Not automated | — | — |
| 11 | Netcheck CDR Voice and Speech Analysis 2026 Q2 NSA vs SA Campaign 7 Cities and London | — | — | Preserved section divider | — | — |
| 12 | Voice Failures 7 Cities | CDR-Voice | `Call_Status` | Stacked horizontal count bar | Failed/Dropped; Classic call, MultiRAB, WhatsApp | Call family × Operator × Campaign |
| 12 | Voice Failures 7 Cities | CDR-Voice | `Failure_Technology` | Stacked horizontal count bar | Failed/Dropped; Classic call, MultiRAB, WhatsApp | Call family × Failure technology × Operator × Campaign |
| 13 | Voice Failures (Vodafone UK) 7 Cities | CDR-Voice | `Call_Status` | Stacked horizontal count bar | Failed/Dropped; Operator Vodafone UK | Call family × City × Campaign |
| 13 | Voice Failures (Vodafone UK) 7 Cities | CDR-Voice | `Failure_Technology` | Stacked horizontal count bar | Failed/Dropped; Operator Vodafone UK | Call family × Failure technology × Campaign |
| 13 | Voice Failures (Vodafone UK) 7 Cities | CDR-Voice | `Failure_Category` | Stacked horizontal count bar | Failed/Dropped; Operator Vodafone UK | Call family × Failure category × Campaign |
| 14 | Completed Call Ratio 7 cities | CDR-Voice | `Call_Status` | 100% stacked column | Classic call, MultiRAB, WhatsApp | Call family × Operator × Campaign |
| 15 | POLQA <1.6 Rate 7 cities | CDR-Speech | `LQ` | 100% stacked column | LQ < 1.6 vs ≥ 1.6 | Call family × Operator × Campaign |
| 16 | POLQA <1.6 Rate Vodafone (Whatsapp) 7 cities | CDR-Speech | `LQ` | Stacked quality-rate column | Operator Vodafone UK; WhatsApp; LQ < 1.6; NR band | NR band |
| 16 | POLQA <1.6 Rate Vodafone (Whatsapp) 7 cities | CDR-Speech | `LQ` vs `Playing_RSRP_NR_Avg` | Scatter | Operator Vodafone UK; WhatsApp; NR samples | Radio strength × LQ state |
| 16 | POLQA <1.6 Rate Vodafone (Whatsapp) 7 cities | CDR-Speech | `LQ` vs `4G_RSRP_Avg_A` | Scatter | Operator Vodafone UK; WhatsApp; LTE samples | Radio strength × LQ state |
| 17 | POLQA <1.6 Rate Three UK (Whatsapp) 7 cities | CDR-Speech | `LQ` | 100% stacked column | Operator Three UK; WhatsApp; LQ < 1.6 vs ≥ 1.6 | Campaign |
| 17 | POLQA <1.6 Rate Three UK (Whatsapp) 7 cities | CDR-Speech | `LQ` | CDF line | Operator Three UK; WhatsApp | Campaign |
| 18 | POLQA Avg MOS 7 cities | CDR-Voice | `POLQA_LQ_Avg` | CDF line | Classic call or MultiRAB | Operator × Campaign |
| 18 | POLQA Avg MOS 7 cities | CDR-Voice | `POLQA_LQ_Avg` | Average-MOS column | Classic call or MultiRAB | Operator × Campaign |
| 18 | POLQA Avg MOS 7 cities | CDR-Speech | `LQ` | CDF line | WhatsApp | Operator × Campaign |
| 18 | POLQA Avg MOS 7 cities | CDR-Speech | `LQ` | Average-MOS column | WhatsApp | Operator × Campaign |
| 19 | POLQA Avg MOS London | CDR-Voice | `POLQA_LQ_Avg` | CDF line | Classic call or MultiRAB; location London | Operator × Campaign |
| 19 | POLQA Avg MOS London | CDR-Voice | `POLQA_LQ_Avg` | Average-MOS column | Classic call or MultiRAB; location London | Operator × Campaign |
| 19 | POLQA Avg MOS London | CDR-Speech | `LQ` | CDF line | WhatsApp; location London | Operator × Campaign |
| 19 | POLQA Avg MOS London | CDR-Speech | `LQ` | Average-MOS column | WhatsApp; location London | Operator × Campaign |
| 20 | Netcheck CDR Data Analysis 2026 Q2 NSA vs SA Campaign 7 Cities and London | — | — | Preserved section divider | — | — |
| 21 | FDFS Success Ratio | CDR-Data | `Test_Result` | 100% stacked column | FDFS; Direction DL; 7 cities | Operator × Campaign |
| 21 | FDFS Success Ratio | CDR-Data | `Test_Result` | 100% stacked column | FDFS; Direction UL; London | Operator × Campaign |
| 22 | FDFS DL Throughput 7 Cities | CDR-Data | `Mean_Data_Rate` | CDF line | FDFS; Direction DL | Operator × Campaign |
| 22 | FDFS DL Throughput 7 Cities | CDR-Data | `Data_Test_Duration` | Average transfer-time column | FDFS; Direction DL | Operator × Campaign |
| 23 | FDFS UL Throughput 7 Cities | CDR-Data | `Mean_Data_Rate` | CDF line | FDFS; Direction UL | Operator × Campaign |
| 23 | FDFS UL Throughput 7 Cities | CDR-Data | `Data_Test_Duration` | Average transfer-time column | FDFS; Direction UL | Operator × Campaign |
| 24 | FDTT DL and UL Throughput 7 Cities | CDR-Data | `FDTT_Sustainable_MDR` | CDF line | FDTT; Directions DL and UL | Operator × Campaign |
| 24 | FDTT DL and UL Throughput 7 Cities | CDR-Data | `FDTT_Sustainable_MDR` | Stacked low-rate distribution | FDTT; Directions DL and UL; template rate buckets | Operator × Campaign × Rate bucket |
| 25 | Interactivity KPIs 7 Cities | CDR-Data | `Interactivity_RTT_Median` | CDF line | Interactivity tests | Operator × Campaign |
| 25 | Interactivity KPIs 7 Cities | CDR-Data | `Interactivity_RTT_Median` | Median RTT column | Interactivity tests | Operator × Campaign |
| 25 | Interactivity KPIs 7 Cities | CDR-Data | `Interactivity_Packet_Error_Ratio` | CDF line | Interactivity tests | Operator × Campaign |
| 25 | Interactivity KPIs 7 Cities | CDR-Data | `Interactivity_Packet_Error_Ratio` | Average packet-error-ratio column | Interactivity tests | Operator × Campaign |
| 26 | Browsing Time to 1MB 7 cities | CDR-Data | `http_Browser_1MB_Reached_Duration` | CDF line | Browsing/HTTP tests | Operator × Campaign |
| 26 | Browsing Time to 1MB 7 cities | CDR-Data | `http_Browser_1MB_Reached_Duration` | Average time-to-1MB column | Browsing/HTTP tests | Operator × Campaign |
| 27 | Conclusions | — | — | Preserved conclusions | — | — |
| 28 | Closing slide | — | — | Preserved closing slide | — | — |
