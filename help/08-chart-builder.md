# Chart Builder

Chart Builder is the ad-hoc chart editor. It reuses the Interactive Preview from E2E Reporting and Slides Template editing, but its definition is temporary: it never changes a stored template or creates a PowerPoint report.

## Workflow

1. Open **Chart Builder** with a workspace active.
2. Choose **CDR Type**: Data, Voice or Speech.
3. Select one or more processed datasets of that type.
4. Choose a KPI and chart type.
5. Add filters with Filter Builder.
6. Select ordered Rows and Columns dimensions.
7. Choose a Legend and Legend Position when required.
8. Enter a Chart Title and review the regenerated preview.

The CDR Source selector is filtered by CDR Type and shows only processed datasets of that type.

## Interactive Preview

| Control | Behaviour |
| --- | --- |
| Chart Title | Text displayed above the generated chart. |
| Chart Type | Bar, CDF, scatter or table renderer. |
| KPI | Field available in the selected sources. |
| Filters | Shared Filter Builder; conditions are joined with AND. |
| Rows | Ordered multi-select for chart categories. |
| Columns | Ordered multi-select for comparison series. |
| Legend | Chart dimension or filter field to explain. |
| Legend Position | Top, Bottom, Left or Right. |

Rows and Columns preserve checkbox order. Selecting `Operator` then `Campaign` produces `Operator × Campaign`.

## Example

```text
CDR Type: Data
Datasets: NetCheck_CDR_Data_2026_Q1.xlsx, NetCheck_CDR_Data_2026_Q2.xlsx
Chart Type: CDF Line
KPI: Mean_Data_Rate
Filters: Test_Result IN (Completed, Dropped, Failed);
Rows: Operator
Columns: Campaign
Legend: Campaign
Legend Position: Bottom
```

## Filter Builder

- Field and operator selectors are searchable.
- **Add filter condition** creates another searchable field selector.
- `IN` and `NOT IN` values may be entered with or without parentheses.
- The parsed filter appears below the builder, one condition per line.
- Empty, null and NaN values are excluded from result-state calculations.

## Performance and troubleshooting

- Title, legend-position and aggregation changes reuse unchanged data where possible.
- Dataset or filter changes invalidate the relevant cache stage.
- Superseded browser preview requests are cancelled.
- If no source appears, process a dataset and select its matching CDR Type.
- If a chart is empty, inspect filtered data and verify KPI, technology and filter values.

Use E2E Reporting for persistent Chart Sets and Slides Template Editor for reusable definitions.
