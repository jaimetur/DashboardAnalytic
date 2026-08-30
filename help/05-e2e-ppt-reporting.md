# 5. E2E PowerPoint Reporting

Dashboard Analytic supports a generic dashboard export and a template-backed NetCheck CDR report. The latter is available from **E2E PowerPoint Reporting → NetCheck CDR Reports**.

## Before generating a NetCheck report

Upload and process the required files in Workspace first:

- one or more `CDR-Data` workbooks;
- one or more `CDR-Voice` workbooks;
- one or more `CDR-Speech` workbooks.

The Reporting selectors default to the latest ready CDR of each type, but support multiple selection. Use Ctrl/Cmd-click to select additional workbooks. Selected Data CDRs are concatenated into the CDR-Data source, and the same happens independently for Voice and Speech. The combination uses the union of available columns, so a field that is absent from one campaign remains available for rows from campaigns that contain it. Existing `Campaign` values are retained, enabling comparisons such as 2025 Q4, 2026 Q1 and 2026 Q2 in the same report.

Before the report applies catalogue filters and groupings, it also consolidates recognised historical UK operator aliases in its in-memory data. Thus `Vodafone` and `Vodafone UK` appear as `Vodafone`; `O2(UK)` and `o2 - de` as `O2`; `3`, `Three` and `three(uk)` as `3`; and EE variants as `EE`. A catalogue filter such as `Operator IN (Vodafone, O2, 3, EE)` therefore matches all of those variants. This is a report-only compatibility layer and does not rename any Workspace dataset.

For a Multivendor report, also process the relevant **VFUK Vodafone UK** and/or **3UK Three UK** mappings, then apply them while importing each CDR or use **Map Vendors** from the Workspace queue later. The reporting page no longer selects mapping files: it uses the Vendor values persisted on the selected CDRs. Multivendor remains disabled until all three selected CDRs have been mapped.

## Report options

Choose the technology according to the required session scope:

| Technology | CDR session filter |
| --- | --- |
| **NSA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `ENDC`. |
| **SA** | `RAT`, `RAT_A` or `Sample_RAT_A` contains `NR`. |

Then choose a report scope:

- **Single-vendor** generates the operator analysis without further mapping requirements.
- **Multivendor** is available only when every selected CDR already contains a Vendor mapping. It creates vendor series where applicable, while keeping O2/EE as operator comparisons. During rendering, template grouping dimensions named `Operator` become `Vendor`; legends named `Operator` become `Campaign`; and occurrences of `Operator` in slide titles, subtitles and chart titles become `Vendor`. `Operator` filters are deliberately not changed and continue to filter the source CDR Operator field.

Choose **Slides Templates** as well. The technology's default template is preselected; another stored NSA or SA template can be chosen for that run without changing the workspace default.

## Vendor calculation

For Vodafone and Three, the report derives vendor from the first and last value available in CDR `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI` and the corresponding mapping. During 3UK processing, Workspace materialises `GCID` from the same value as `Cid__ECI` (or `CId___ECI`). During VFUK processing, it materialises the 4G GCID as `eNodeB ID × 256 + Local Cell ID`; this is equivalent to `HEX2DEC(DEC2HEX(eNodeB ID, 5) & DEC2HEX(Local Cell ID, 2))` in Excel. It also materialises the existing 5G convention, `gNodeB ID × 4096 + Local Cell ID`, for inspection in the mapping preview. The report's Vodafone lookup remains based on the agreed 4G mapping formula. The agreed business formula is authoritative: matching mapped endpoints yield that vendor; Vodafone explicitly distinguishes Ericsson-related mixed cases, other mixed cases and missing endpoints; Three uses a mixed-vendor result for non-matching endpoints. O2 and EE remain represented as the operator.

## Generated presentation

Every NSA, SA, single-vendor and multivendor report uses the same `assets/ppt-templates/Template_CDR_analysis.pptx` (or the file with that name under `APP_PPT_TEMPLATES_DIR`). It is a master/layout-only template and intentionally contains no slides. For every distinct `Slide` number in the selected Slides Templates, the renderer creates one new slide from its named layout, ordered by slide number. Rows with the same number represent separate charts on that slide and fill its image placeholders from left to right and then top to bottom. Commentary placeholders remain blank for analyst input.

An administrator can manage several named NSA and SA Slides Templates CSVs. A template can be set as the default, duplicated, renamed, deleted or exported, then edited directly in the browser. Every CDR row represents one chart image and declares its named PowerPoint `Layout`; the renderer creates the slide, populates its title and places generated charts in the layout's matching chart placeholders. Importing or selecting a new default template refreshes the tables below.

After generation, the timestamp-named PPTX downloads through the browser and the generation dialog closes. If the report contains no valid samples, re-check the selected technology, operator sheets and CDR inputs; the message indicates that the selected persisted rows did not match the relevant KPI and technology filter. For NSA, validate that the relevant RAT field actually contains an ENDC variant; for SA, validate the expected `NR` values.

## Slides Templates and chart contract

The renderer follows the visual grammar of the supplied template for every automated KPI slide: 100% stacked columns for success/quality splits, stacked count bars for failures, CDF lines for continuous KPIs, vertical bars for mean or median comparisons, distribution bars for FDTT rate buckets, and band/radio-quality scatter plots on the dedicated SA Vodafone analysis. Operator colours remain consistent with the template: 3UK orange, EE blue, VFUK red and O2 purple. `Campaign` (or the processed `period` fallback) is the benchmark/category dimension; a multivendor run replaces the operator series with the calculated operator-vendor series.

The technology condition below is always applied before the slide-level filters: NSA contains an ENDC spelling in `RAT`, `RAT_A` or `Sample_RAT_A`; SA contains `NR` in the same fields.

The current CSV schema is `Slide`, `Slide tittle`, `Slide Subtittle`, `Layout`, `Chart Tittle`, `CDR source`, `KPI`, `Chart type`, `Legend`, `Filters`, `Grouping_Rows` and `Grouping_Columns`. For automated rows, all chart-definition fields are executable. `Slide Subtittle` is rendered in the second line of a chart slide's title placeholder in smaller blue text; `Chart Tittle` is the chart heading; `Legend` can replace generated captions in comma-separated order.

Two structural `Chart type` values build non-KPI slides:

- `Title Slide` creates the presentation cover, normally with the `Title Page` layout. `Slide tittle` and `Slide Subtittle` populate the layout's title and subtitle placeholders.
- `Transition Slide` creates a section divider, normally with `Title Only` or another suitable transition layout. It accepts a title and optional subtitle.

A structural slide occupies exactly one template row and cannot share its slide number with chart rows. Leave `Chart Tittle`, `CDR source`, `KPI`, `Legend`, `Filters`, `Grouping_Rows` and `Grouping_Columns` empty. The former `Not Automated (preserve)` value is retained only for legacy conversion: imported legacy rows are migrated to `Title Slide` or `Transition Slide`, because an empty template has no source slide to preserve.

Write filters as semicolon-separated expressions such as `Call Family IN (VoLTE, MultiRAB); Direction = DL` or `Type_of_Test = Interactivity`. Supported operators are `IN (...)`, `NOT IN (...)`, `CONTAINS`, `NOT CONTAINS`, `=`, `!=`, `<`, `<=`, `>` and `>=`. Use processed CDR column names (case-insensitive matching is supported). `Call Family` is a supported derived dimension: the NetCheck CDR values `CALL`, `MultiRAB CALL` and `WhatsApp CALL` are normalised to their test families, with the classic-call mode resolving VoLTE or VoNR where available. `Threshold = 1.6` configures `Threshold Stacked Vertical Bars`, while `Buckets = 1,5,20,100` configures `Rate Bucket` for `Distribution Stacked Vertical Bars`.

Write each grouping hierarchy with `×`. `Grouping_Rows` defines the visible category/table-row hierarchy. `Grouping_Columns` defines comparison series and table columns; if it is empty, the renderer uses one `(all)` series and does not duplicate category labels. For distribution charts the final column dimension is the stack/bucket breakdown. This interpretation is consistent across CDF, scatter, mean/median bars, stacked status/failure/distribution bars and tables. `Operator` resolves to the calculated operator-vendor comparison field in multivendor reports. The valid automated chart types are `100% Stacked Vertical Bars`, `Count Stacked Horizontal Bars`, `CDF Line`, `Scatter`, `Table`, `Average Vertical Bars`, `Median Vertical Bars`, `Distribution Stacked Vertical Bars` and `Threshold Stacked Vertical Bars`; the structural types are `Title Slide` and `Transition Slide`.

The importer accepts the current schema and compatible legacy schemas. If the headers differ, it presents a conversion confirmation: compatible names are migrated, legacy `Grouping` is split into row/column grouping, new optional presentation fields remain blank, and a missing layout is assigned from the number of CDR charts on that slide. Any remaining invalid chart contract is presented in a floating import-failure dialog.

<!-- SLIDES_TEMPLATES:START -->

Export the active NSA or SA Slides Template from Admin before editing it. The tables below always reflect the active CSV files under `assets/slides-templates/default/`.

### NSA template

| Slide | Slide tittle | Slide Subtittle | Layout | Chart Tittle | CDR source | KPI | Chart type | Legend | Filters | Grouping_Rows | Grouping_Columns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | First | — | Title and 1 column + Comments | — | CDR-Voice | Call_Status | 100% Stacked Vertical Bars | — | — | Operator | Campaign |

### SA template

| Slide | Slide tittle | Slide Subtittle | Layout | Chart Tittle | CDR source | KPI | Chart type | Legend | Filters | Grouping_Rows | Grouping_Columns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | NPPI Tech Forum<br>VodafoneThree & Ericsson<br>2026-08-06 | 2026 Q2 Net check 5G SA Campaign<br>Final Scoring and Gap Analysis<br>CDR KPI Analysis | Title Page | — | — | — | Title Slide | — | — | — | — |
| 2 | Agenda | — | Title Only | — | — | — | Transition Slide | — | — | — | — |
| 3 | Voice Failures | 7 Cities | Title and 2 columns | — | CDR-Voice | Call_Status | Count Stacked Horizontal Bars | — | Failed/Dropped; Classic call, MultiRAB, WhatsApp | Call family | Operator × Campaign |
| 3 | Voice Failures | 7 Cities | Title and 2 columns | — | CDR-Voice | Failure_Technology | Count Stacked Horizontal Bars | — | Failed/Dropped; Classic call, MultiRAB, WhatsApp | Call family | Failure technology × Operator × Campaign |
| 4 | Voice Failures (Vodafone UK) | 7 Cities | Title and 3 columns | — | CDR-Voice | Call_Status | Count Stacked Horizontal Bars | — | Failed/Dropped; Operator Vodafone UK | Call family | City × Campaign |
| 4 | Voice Failures (Vodafone UK) | 7 Cities | Title and 3 columns | — | CDR-Voice | Failure_Technology | Count Stacked Horizontal Bars | — | Failed/Dropped; Operator Vodafone UK | Call family | Failure technology × Campaign |
| 4 | Voice Failures (Vodafone UK) | 7 Cities | Title and 3 columns | — | CDR-Voice | Failure_Category | Count Stacked Horizontal Bars | — | Failed/Dropped; Operator Vodafone UK | Call family | Failure category × Campaign |
| 5 | Completed Call Ratio | 7 cities | Title and 1 smaller column | — | CDR-Voice | Call_Status | 100% Stacked Vertical Bars | — | Classic call, MultiRAB, WhatsApp | Call family | Operator × Campaign |
| 6 | POLQA <1.6 Rate | 7 cities | Title and 1 smaller column | — | CDR-Speech | LQ | 100% Stacked Vertical Bars | — | LQ < 1.6 vs ≥ 1.6 | Call family | Operator × Campaign |
| 7 | POLQA <1.6 Rate Vodafone (Whatsapp) | 7 cities | Title and 3 columns | — | CDR-Speech | LQ | Threshold Stacked Vertical Bars | — | Operator Vodafone UK; WhatsApp; LQ < 1.6; NR band | NR band | — |
| 7 | POLQA <1.6 Rate Vodafone (Whatsapp) | 7 cities | Title and 3 columns | — | CDR-Speech | LQ vs Playing_RSRP_NR_Avg | Scatter | — | Operator Vodafone UK; WhatsApp; NR samples | Radio strength | LQ state |
| 7 | POLQA <1.6 Rate Vodafone (Whatsapp) | 7 cities | Title and 3 columns | — | CDR-Speech | LQ vs 4G_RSRP_Avg_A | Scatter | — | Operator Vodafone UK; WhatsApp; LTE samples | Radio strength | LQ state |
| 8 | POLQA <1.6 Rate Three UK (Whatsapp) | 7 cities | Title and 2 columns | — | CDR-Speech | LQ | 100% Stacked Vertical Bars | — | Operator Three UK; WhatsApp; LQ < 1.6 vs ≥ 1.6 | Campaign | — |
| 8 | POLQA <1.6 Rate Three UK (Whatsapp) | 7 cities | Title and 2 columns | — | CDR-Speech | LQ | CDF Line | — | Operator Three UK; WhatsApp | Campaign | — |
| 9 | POLQA Avg MOS | 7 cities | Title and 8 Content | — | CDR-Voice | POLQA_LQ_Avg | CDF Line | — | Classic call or MultiRAB | Operator | Campaign |
| 9 | POLQA Avg MOS | 7 cities | Title and 8 Content | — | CDR-Voice | POLQA_LQ_Avg | Average Vertical Bars | — | Classic call or MultiRAB | Operator | Campaign |
| 9 | POLQA Avg MOS | 7 cities | Title and 8 Content | — | CDR-Speech | LQ | CDF Line | — | WhatsApp | Operator | Campaign |
| 9 | POLQA Avg MOS | 7 cities | Title and 8 Content | — | CDR-Speech | LQ | Average Vertical Bars | — | WhatsApp | Operator | Campaign |
| 10 | POLQA Avg MOS | London | Title and 8 Content | — | CDR-Voice | POLQA_LQ_Avg | CDF Line | — | Classic call or MultiRAB; location London | Operator | Campaign |
| 10 | POLQA Avg MOS | London | Title and 8 Content | — | CDR-Voice | POLQA_LQ_Avg | Average Vertical Bars | — | Classic call or MultiRAB; location London | Operator | Campaign |
| 10 | POLQA Avg MOS | London | Title and 8 Content | — | CDR-Speech | LQ | CDF Line | — | WhatsApp; location London | Operator | Campaign |
| 10 | POLQA Avg MOS | London | Title and 8 Content | — | CDR-Speech | LQ | Average Vertical Bars | — | WhatsApp; location London | Operator | Campaign |
| 11 | Netcheck CDR Data Analysis | 2026 Q2 NSA vs SA Campaign<br>7 Cities and London | Title Only | — | — | — | Transition Slide | — | — | — | — |
| 12 | FDFS Success Ratio | — | Title and 2 columns | — | CDR-Data | Test_Result | 100% Stacked Vertical Bars | — | FDFS; Direction DL; 7 cities | Operator | Campaign |
| 12 | FDFS Success Ratio | — | Title and 2 columns | — | CDR-Data | Test_Result | 100% Stacked Vertical Bars | — | FDFS; Direction UL; London | Operator | Campaign |
| 13 | FDFS DL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | Mean_Data_Rate | CDF Line | — | FDFS; Direction DL | Operator | Campaign |
| 13 | FDFS DL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | Data_Test_Duration | Average Vertical Bars | — | FDFS; Direction DL | Operator | Campaign |
| 14 | FDFS UL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | Mean_Data_Rate | CDF Line | — | FDFS; Direction UL | Operator | Campaign |
| 14 | FDFS UL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | Data_Test_Duration | Average Vertical Bars | — | FDFS; Direction UL | Operator | Campaign |
| 15 | FDTT DL and UL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | FDTT_Sustainable_MDR | CDF Line | — | FDTT; Directions DL and UL | Operator | Campaign |
| 15 | FDTT DL and UL Throughput | 7 Cities | Title and 2 columns | — | CDR-Data | FDTT_Sustainable_MDR | Distribution Stacked Vertical Bars | — | FDTT; Directions DL and UL; template rate buckets | Operator | Campaign × Rate bucket |
| 16 | Interactivity KPIs | 7 Cities | Title and 8 Content | — | CDR-Data | Interactivity_RTT_Median | CDF Line | — | Interactivity tests | Operator | Campaign |
| 16 | Interactivity KPIs | 7 Cities | Title and 8 Content | — | CDR-Data | Interactivity_RTT_Median | Median Vertical Bars | — | Interactivity tests | Operator | Campaign |
| 16 | Interactivity KPIs | 7 Cities | Title and 8 Content | — | CDR-Data | Interactivity_Packet_Error_Ratio | CDF Line | — | Interactivity tests | Operator | Campaign |
| 16 | Interactivity KPIs | 7 Cities | Title and 8 Content | — | CDR-Data | Interactivity_Packet_Error_Ratio | Average Vertical Bars | — | Interactivity tests | Operator | Campaign |
| 17 | Browsing Time to 1MB | 7 cities | Title and 2 columns | — | CDR-Data | http_Browser_1MB_Reached_Duration | CDF Line | — | Browsing/HTTP tests | Operator | Campaign |
| 17 | Browsing Time to 1MB | 7 cities | Title and 2 columns | — | CDR-Data | http_Browser_1MB_Reached_Duration | Average Vertical Bars | — | Browsing/HTTP tests | Operator | Campaign |
| 18 | Conclusions | — | Title Only | — | — | — | Transition Slide | — | — | — | — |

<!-- SLIDES_TEMPLATES:END -->
