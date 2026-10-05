# Datasets Analysis

Datasets Analysis provides on-demand KPI analysis for one processed CDR in the active workspace.

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

Mappings, logs and generic datasets are excluded from the Datasets Analysis selector.

## Analysis workflow

1. Select a processed dataset.
2. Choose one or more KPI-like numeric fields.
3. Apply the available categorical/date filters.
4. Choose an aggregation where offered.
5. Click **Update Analysis**.
6. Confirm the filtered sample count.
7. Review charts, scorecards and processed metrics.
8. Export only after validating the analytical context.

## Analysis Controls

Controls adapt to the selected dataset.

- Geographic and operator dimensions appear only when present.
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

- **CDF Curve** shows the empirical KPI distribution.
- **Group Benchmark** compares the selected aggregation.
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
| Derived fields, including Vendor and Vendor_Only | Light green. |
| Auto-calculated Fields | Purple. |

Empty fixed, derived and Auto-calculated fields remain visible. Stronger header colours distinguish labels from values. After origin fields, Preview groups the identity/fixed fields, Auto-calculated Fields, other derived fields and remaining source fields.

### Read field values correctly

- Field references ignore letter case and differences between spaces, underscores and hyphens. Subscriber also accepts the legacy Suscriber spelling.
- Campaign source text is preserved. Recognised chart/filter labels can use YYYY-Qn, YYYY-Qn_SA or YYYY-Qn_NSA; equality keeps these three campaign forms separate.
- Campaign Year, Campaign Quarter, Period and Market derive from Campaign with a Benchmark fallback.
- Zone and City fall back to G_Level_3 and G_Level_4 when their source field is empty.
- Event Start/End values use YYYY-MM-DD HH:MM:SS.ffffff.

### Export the analysis

**Summary PowerPoint** and **Summary Word** create one document with every KPI of each selected dataset, without filters: a dialog lists the ready CDR datasets, all selected by default. The same Summary Dataset Analysis is available as a [Reporting](reporting.md) artifact.

Word and PowerPoint exports reflect the current analysis request. Analysis filters do not overwrite stored dataset rows. For a complete template-driven report, use E2E Dashboards or the restricted Reporting (old) workflow.

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

- Opening the page reads cached metadata.
- Full analysis starts only after **Update Analysis**.
- Repeated dataset/filter/metric combinations reuse in-memory cache entries.
- Large caches are process-local and are cleared by an application restart.
