# 4. E2E Dashboard

E2E Dashboard is the interactive layer for a processed NetCheck CDR dataset. It adapts to the available CDR columns, so filter values and KPIs can differ between Data, Voice and Speech sources.

## Typical analysis flow

1. Open **E2E Dashboard**.
2. Select a processed `CDR-Data`, `CDR-Voice` or `CDR-Speech` dataset from the workspace. Mappings, logs and Other datasets are not Dashboard candidates.
3. Filter by market, operator, period, technology, vendor or other categorical fields available in the source.
4. Select one or more KPI-like numeric fields and, where available, choose the CDF and comparison aggregation. Coordinates, cell identifiers, locations and other technical metadata are deliberately excluded from the metric list.
5. Review global and per-metric summary cards, percentile values, CDF curves, comparison charts and the filtered record table.
6. Use **Preview Dataset** when raw persisted values need checking; it opens the same new-tab preview as Workspace.
7. Export only after validating the active dataset, filters, metrics and scope.

## Available KPI outputs

The analytics layer provides numeric metric selection, global and per-metric KPI cards, percentile scorecards, CDF payloads, comparison charts and a filtered record table. Market, period, date range and other adaptive dimensions are offered only when the selected data contains the corresponding columns. The application opens cached dataset metadata quickly; full charts and tables are calculated when **Update Dashboard** is requested.

## Good practice

- Start broad, then narrow the filters one at a time to detect unexpected changes.
- Check sample counts before comparing distributions or percentile values.
- Keep the dataset name, active filters and selected aggregation with any exported result.
- If a required filter or KPI is missing, verify the source workbook and its ingestion status first.
- Use the sample count as the first check when a chart appears empty or a percentile comparison is not meaningful.

The Dashboard is the extension point for future NetCheck scoring and GAP analysis; those sections are deliberately not automated in the CDR reporting flow yet.
