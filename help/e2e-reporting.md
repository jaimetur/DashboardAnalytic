# E2E Reporting

Use **E2E Reporting → NetCheck CDR Reports** to create a persistent PowerPoint Report or standalone Chart Set from processed CDR-Data, CDR-Voice and CDR-Speech datasets.

E2E Reporting is available to super-admins and the EJAITUR user when a workspace is active. The module menu and this Help chapter are hidden from other users. The canonical route is `/e2e-reporting`; `/reporting` bookmarks redirect there and the API uses `/api/e2e-reporting`.

## Before generating

Process at least one suitable CDR. Reporting can combine multiple datasets of one type and retains Campaign for comparisons. Reports may use any non-empty combination of Data, Voice and Speech; template rows without a selected source render an explicit unavailable-source placeholder.

Select NR Mode:

| NR Mode | Included sessions |
| --- | --- |
| NSA | Voice/Speech sessions classified through recognised ENDC/NSA RAT or Call Mode values. |
| SA | Voice/Speech sessions classified through recognised NR/SA RAT or Call Mode values. |

Valid Data attempts remain available even when sample RAT records a fallback.

Select Scope:

- **Operator Comparison** uses normalized Operator.
- **Multivendor Comparison** requires Vendor mapping for every selected CDR.
- In Multivendor, Operator aggregation resolves to the mapped operator/vendor comparison field; an Operator template filter still applies to the physical Operator column.

Operator Comparison initially selects the two newest CDRs of each type, or the only available one. Changing to Multivendor keeps one selected CDR per type. An existing single selection is preserved even when it is not the newest.

## Report Template selection

Choose an NSA/SA Report Template from the active workspace. Each template controls slides, layouts, CDR sources, chart types, KPIs, filters, aggregations and legends. Administrators manage and edit templates in Admin; new workspaces have none until a template is created or imported.

For the complete schema, supported chart types, examples, Filter Builder language, aggregations, legends, multi-chart slides and colour rules, see [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

## Generate PowerPoint Report

Enter the report name, choose datasets, NR Mode, scope and template, then queue generation. The job creates:

```text
output/reports/<report-name>/
  <report-name>.pptx
  report-charts/
```

The PPTX uses `Template_CDR_analysis.pptx` masters/layouts and the selected Report Template definition. Commentary placeholders remain available to the analyst.

## Generate Report Charts

This queues a standalone Chart Set under:

```text
output/charts/<generation>/
```

Chart Sets use the same datasets, NR Mode, scope, template and renderer as Reports without building the final PowerPoint.

## Reports and Charts Jobs

Reports and Chart Sets share the workspace `generated_jobs` table and are distinguished by Type. The table supports Excel-style filters for ID, Date, NR Mode, Type, Template, Scope and other displayed fields.

Actions depend on job state: open, download, stop, retry, relaunch or delete. If an interrupted job has valid deterministic PNG and tooltip files, retry keeps completed assets and renders only missing or invalid charts. Deliberately relaunching a completed job starts clean.

## Charts Panel

Charts Panel browses report-rendered and standalone Chart Sets. Filter by NR Mode, Type, Template and Scope, then select a generated set.

- Open thumbnails in the shared expanded Interactive Preview.
- Hover over the chart canvas to reveal its top-right controls: the filtered-dataset icon followed by zoom controls. They remain visible while interacting and hide three seconds after the pointer leaves the canvas. The dataset panel opens immediately while the floating **Loading Filtered Dataset** dialog reports its preparation, fills its parent viewer with a 2% inset on every side, provides server-side pagination and column filters, and reuses the selected Chart Set's cached CDR source when moving between charts of the same type.
- Download or delete a Chart Set.
- Administrators can open the exact source template and row.
- Temporary preview changes do not modify the stored template until Update Template and Save are used in the editor.

Reports, Chart Sets, Dashboard exports and interactive previews share the Dashboard Canvas renderer for consistent geometry, colours, hierarchy, legends and semantic tooltips. `DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER=pil` enables the legacy server painter when required.

## Troubleshooting

- Missing CDR: verify the active workspace, dataset type and Processed status.
- Multivendor unavailable: persist Vendor mapping for every selected CDR.
- Empty chart: inspect the filtered dataset and the template row referenced in [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).
- Invalid template: use the editor's `Slide: n - Chart: n` validation message.
- Failed or interrupted job: inspect App Logs, then retry the existing job.
