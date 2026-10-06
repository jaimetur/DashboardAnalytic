# CDR Analysis

CDR Analysis provides on-demand KPI analysis for one processed CDR in the active workspace.

> [!NOTE]
> **One dataset at a time.** Use this module for a focused investigation of one processed Data, Voice or Speech CDR. Use E2E Dashboards for a complete template across multiple datasets.

> [!TIP]
> **Inspect before exporting.** Update Analysis after changing the controls, then inspect sample counts and the filtered records.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Eligible datasets | [Open section](#eligible-datasets) |
| Analysis workflow | [Open section](#analysis-workflow) |
| Analysis Controls | [Open section](#analysis-controls) |
| Dataset Summary | [Open section](#dataset-summary) |
| Charts and Scorecards | [Open section](#charts-and-scorecards) |
| Processed Metrics | [Open section](#processed-metrics) |
| Preview and export | [Open section](#preview-and-export) |
| Example investigation | [Open section](#example-investigation) |
| Performance | [Open section](#performance) |

## Eligible datasets

- CDR-Data
- CDR-Voice
- CDR-Speech

Mappings, logs and generic datasets are excluded from the CDR Analysis selector.

## Analysis workflow

1. Select a processed dataset.
2. Choose one or more metrics; every available metric is selected by default.
3. Apply the available categorical/date filters.
4. Choose an aggregation where offered.
5. Click **Update Analysis**.
6. Confirm the filtered sample count.
7. Review charts, scorecards and processed metrics.
8. Export only after validating the analytical context.

## Analysis Controls

Controls adapt to the selected dataset.

- **Metrics** lists only measurements: the service KPIs first (POLQA LQ, LQ, Mean Data Rate, call setup time, delays, RTT, throughput, jitter and packet loss), then the radio and service measurements of the CDR (RSRP, RSRQ, SINR, CQI, MCS, BLER, transmit power and throughput averages). Identifiers, phone numbers, IMEI/IMSI/MSISDN, software versions, timestamps, durations, transferred bytes, bands, PCI/ARFCN, quarters, speeds and minimum or maximum columns are not offered. Every available metric is selected by default.
- Filters follow the order Source Sheet, Operator, **Operator_Vendor** (`<Operator>_<Vendor>`), **Vendor** (the vendor alone), Market, Region, **Cluster**, City, Test Name and the remaining dimensions; dimensions without values in the CDR are disabled. Every filter lists the values found in the rows of the open CDR.
- **Open Dataset** shows the analysis at once. The last metrics and filters applied with **Update Analysis** to each CDR are shared by every user of the workspace and restored in every session; **Reset** clears them and shows the default analysis.
- Date ranges appear only when a usable date field exists.
- Technical identifiers and coordinates are not offered as KPIs.
- Filter choices are retained for the requested analysis, not written back to source data.

## Dataset Summary

- Dataset identity and current context.
- Global summary cards.
- Per-KPI headline values.
- Percentile scorecards.
- Filtered sample counts.

## Charts and Scorecards

- **CDF Curve** shows the empirical KPI distribution. **Global CDF Comparison** and **Compare CDF by** draw one curve per value of the chosen dimension (Operator by default, listed first), up to eight curves.
- **Group Benchmark** compares the selected aggregation. Bar labels that do not fit are rotated.
- Every chart has floating zoom controls in its top-right corner (−, level, + and reset) and, as in E2E Dashboards, zooms into a rectangle dragged over it: a CDF narrows its X and Y range, and a bar chart widens to fit the selected bars and scrolls to them. Hovering a bar shows its value, and hovering a CDF shows the probability of every curve at that value.
- **Visible X Range** has two handles to adjust the start and the end of the CDF axis. By default it starts where the first curve reaches 5% of its samples and ends where every curve reaches 95%, leaving out nearly empty tails; a rectangle zoom moves both handles and reset returns to these defaults.
- **Grouped Percentiles** and **Processed Metrics** show decimal values with two digits; Processed Metrics lists Cluster after Region. Grouped by Operator, Vendor or Operator_Vendor, the tables, the percentiles, the bars and the CDF curves follow the order of the Operator Maps and Vendor Maps tables of Workspace Config; values that are not in the maps follow alphabetically (mixed groups before operators without a vendor).
- Metric cards provide compact numerical summaries.

## Processed Metrics

The table shows the calculated records for the active request. Use it to verify that the chart and KPI cards share the same scope.

## Preview and export

### Inspect persisted rows

**Preview Dataset** opens stored CDR fields in 100-row pages. Use the searchable Dataset selector to switch to another ready dataset.

| Control | Effect |
| --- | --- |
| Column search / field selection | Narrow a wide table without removing rows. |
| Column value menu | Filter using the complete column's distinct values. Filters on different columns combine. |
| Label multiselect | Show selected field families: Derived, Auto-calculated, CDR-Main or source CDR type. |
| Hover / select a field label | Read its rule in a tooltip or the complete rule panel. |

| Field family | Preview appearance |
| --- | --- |
| Source_File, Source_Sheet, Dataset_Kind | Yellow origin fields, shown first. |
| Main CDR fields | Blue, labelled CDR-Main. |
| Derived fields, including Operator_Vendor and Vendor | Light green. |
| Auto-calculated Fields | Purple. |

Empty fixed, derived and Auto-calculated fields remain visible. Stronger header colours distinguish labels from values. After origin fields, Preview groups the identity/fixed fields, Auto-calculated Fields, other derived fields and remaining source fields.

### Read field values correctly

- Field references ignore letter case and differences between spaces, underscores and hyphens. Subscriber also accepts the legacy Suscriber spelling.
- Campaign source text is preserved. Recognised chart/filter labels can use YYYY-Qn, YYYY-Qn_SA or YYYY-Qn_NSA; equality keeps these three campaign forms separate.
- Campaign Year, Campaign Quarter, Period and Market derive from Campaign with a Benchmark fallback.
- Zone and City fall back to G_Level_3 and G_Level_4 when their source field is empty.
- Event Start/End values use YYYY-MM-DD HH:MM:SS.ffffff.

### Export the analysis

**Export PowerPoint** and **Export Word** open one dialog. With **Use the current filters, metrics and chart settings** (checked when an analysis is open) the document is the open CDR exactly as on screen: its metrics and filters, each chart's **Compare by** and **Compare CDF by**, and each CDF's **Visible X Range**. Unchecking it exports the CDRs selected in the dialog (the open CDR by default; CDR Data, Voice and Speech panels with **Select All** each) with every KPI and no filters, the same summary available as a [Reporting](reporting.md) artifact.

Word exports contain the same report as PowerPoint, one landscape page per slide (rendered with LibreOffice when it is installed, as in the Docker image). PowerPoint exports use the workspace PowerPoint template (`assets/ppt-templates/Template_CDR_analysis.pptx`): a title slide names the CDR and lists its type, metrics and every filter, the content slides use the template's title layout and the deck ends with its closing slide. Exported documents are also kept in the `output/reports/cdr-analysis/` folder of the workspace, where an identical export of the open CDR is reused instead of generated again.

Analysis filters do not overwrite stored dataset rows. Analysis filters do not overwrite stored dataset rows. For a complete template-driven report, use E2E Dashboards or the restricted Reporting (old) workflow.

## Example investigation

To compare throughput by operator:

```text
Dataset: CDR-Data 2026-Q2
KPI: Mean_Data_Rate
Filter: Test_Result = Completed
Aggregation: Operator
```

First compare group sample counts. Then inspect the CDF and group benchmark. If a result differs from another tool, reproduce the same row set in Preview and verify null/result-state handling.

## Performance

- Opening the page reads cached metadata; which metrics have values in each CDR is checked once and kept until the CDR changes.
- Full analysis starts only after **Update Analysis**.
- The page shows the first four metrics at once; the other metrics and the Processed Metrics table appear as they are calculated, a few at a time, while you already work with the first ones.
- Repeated dataset/filter/metric combinations reuse in-memory cache entries.
- Large caches are process-local and are cleared by an application restart.
