# KPI analysis

E2E Bench Dashboard is the interactive layer for a processed workspace dataset. It adapts to the columns present in the source, so the available filters and metrics may differ between datasets.

## Typical analysis flow

1. Open **E2E Bench Dashboard**.
2. Select a processed dataset from the workspace.
3. Filter by market, operator, period, technology, vendor or other categorical fields available in the source.
4. Select one or more numeric KPIs and, where available, choose the CDF and comparison aggregation.
5. Review global and per-metric summary cards, percentile values, CDF curves, comparison charts and the filtered record table.
6. Export only after validating the active dataset, filters, metrics and scope.

## Available KPI outputs

The analytics layer provides numeric metric selection, global and per-metric KPI cards, percentile scorecards, CDF payloads, comparison charts and a filtered record table. Market, period, date range and other adaptive dimensions are offered only when the selected data contains the corresponding columns. The application opens cached dataset metadata quickly; full charts and tables are calculated when **Update Dashboard** is requested.

## Good practice

- Start broad, then narrow the filters one at a time to detect unexpected changes.
- Check sample counts before comparing distributions or percentile values.
- Keep the dataset name, active filters and selected aggregation with any exported result.
- If a required filter or KPI is missing, verify the source workbook and its ingestion status first.
- Use the sample count as the first check when a chart appears empty or a percentile comparison is not meaningful.

The Dashboard is the extension point for future NetCheck scoring and GAP analysis; those sections are deliberately not automated in the CDR reporting flow yet.
