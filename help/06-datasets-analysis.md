# Datasets Analysis

Datasets Analysis provides on-demand KPI analysis for one processed CDR in the active workspace.

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

- **Preview Dataset** opens every stored CDR field in 100-row pages. Use the searchable Dataset selector to move to another ready Workspace dataset and the column search to narrow very wide tables. Each column header provides an Excel-style value menu loaded from the complete column; filters can be combined and cleared together. Field names can be referenced with any letter case and with spaces, underscores or hyphens interchangeably; `Subscriber` also resolves the legacy `Suscriber` spelling. Selected text values are case-insensitive. Every preview starts with yellow `Source_File`, `Source_Sheet` and `Dataset_Kind`, followed by Operator, Subscriber, Vendor and Vendor_Only, the other fixed fields, Auto-calculated Fields, other derived fields and finally the remaining source fields. Main CDR fields are blue and labelled `CDR-Main`, derived fields including Vendor and Vendor_Only are light green, and Auto-calculated Fields are purple. Stronger header colours distinguish headings from values. Use the multi-select label filter to show only Derived, Auto-calculated, `CDR-Main` or the active CDR type. Empty fixed, derived and Auto-calculated fields remain visible. Hover a label to see its rule, or select it to open the rule panel.
- Campaign source text is preserved. Filters and chart labels also accept reordered country, year, quarter and SA/NSA forms and expose compact `YYYY-Qn`, `YYYY-Qn_SA` or `YYYY-Qn_NSA` values. Equality keeps base, SA and NSA campaigns separate. Campaign Year, Campaign Quarter, Period and Market use Campaign with a Benchmark fallback; Zone and City fall back to G Level 3 and G Level 4 only when their own source field is empty. Event Start/End values use `YYYY-MM-DD HH:MM:SS.ffffff`.
- Dashboard filters do not overwrite the dataset.
- Word and PowerPoint exports reflect the current Dashboard analysis.
- Template-driven reports belong to E2E Reporting instead.

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
