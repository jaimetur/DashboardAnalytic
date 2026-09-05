# E2E Dashboard

E2E Dashboard provides on-demand KPI analysis for one processed CDR in the active workspace.

## Eligible datasets

- CDR-Data
- CDR-Voice
- CDR-Speech

Mappings, logs and generic datasets are excluded from the Dashboard selector.

## Analysis workflow

1. Select a processed dataset.
2. Choose one or more KPI-like numeric fields.
3. Apply the available categorical/date filters.
4. Choose an aggregation where offered.
5. Click **Update Dashboard**.
6. Confirm the filtered sample count.
7. Review charts, scorecards and processed metrics.
8. Export only after validating the analytical context.

## Dashboard Controls

Controls adapt to the selected dataset.

- Geographic and operator dimensions appear only when present.
- Date ranges appear only when a usable date field exists.
- Technical identifiers and coordinates are not offered as KPIs.
- Filter choices are retained for the requested analysis, not written back to source data.

## Executive Dashboard

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

- **Preview Dataset** opens stored rows and independent preview filters.
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
- Full analysis starts only after **Update Dashboard**.
- Repeated dataset/filter/metric combinations reuse in-memory cache entries.
- Large caches are process-local and are cleared by an application restart.
