# E2E Reporting

Use **E2E Reporting → NetCheck CDR Reports** to create a persistent PowerPoint Report or standalone Chart Set from processed CDR-Data, CDR-Voice and CDR-Speech datasets.

> [!NOTE]
> **Restricted classic workflow.** E2E Reporting is available to super-admin accounts and EJAITUR. E2E Dashboards is the main template-driven analysis workflow.

> [!WARNING]
> **Missing CDR types.** A non-empty CDR selection is enough to generate a job, but charts requiring an unselected source type show an unavailable placeholder.

E2E Reporting is available to super-admins and the EJAITUR user when a workspace is active. The module menu and this Help chapter are hidden from other users. The canonical route is `/e2e-reporting`; `/reporting` bookmarks redirect there and the API uses `/api/e2e-reporting`.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Before generating | [Open section](#before-generating) |
| Report Template selection | [Open section](#report-template-selection) |
| Generate PowerPoint Report | [Open section](#generate-powerpoint-report) |
| Generate Report Charts | [Open section](#generate-report-charts) |
| Reports and Charts Jobs | [Open section](#reports-and-charts-jobs) |
| Charts Panel | [Open section](#charts-panel) |
| Troubleshooting | [Open section](#troubleshooting) |

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

Choose an NSA/SA Report Template from the active workspace. Each template controls slides, layouts, source datasets, chart types, KPIs, filters, aggregations and legends. Authorised users manage and edit templates in Workspace Config; new workspaces have none until a template is created or imported.

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

| Action | Purpose |
| --- | --- |
| Open / download | Review completed output; Download PPT is the highlighted presentation action. |
| Stop | Request interruption when supported by the active job. |
| Retry | Resume an interrupted job, retaining valid PNG/tooltip assets and rendering missing or invalid charts. |
| Relaunch | Start a completed job clean. |
| Delete | Remove the selected generated job and its output. |

## Charts Panel

Charts Panel browses report-rendered and standalone Chart Sets. Filter by NR Mode, Type, Template and Scope, then select a generated set.

- Open thumbnails in the shared expanded Interactive Preview.
- Hover over the chart canvas to reveal the filtered-dataset and zoom controls. They remain visible while interacting and hide three seconds after the pointer leaves.
- Open the dataset panel to inspect server-side pages and column filters. Loading Filtered Dataset reports preparation while the panel opens.
- Moving between charts of the same CDR type reuses the selected Chart Set's cached source.
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

> [!NOTE]
> **Vendor comparison:** Multivendor exports ask whether to compare **Operator – Vendor** identities or pool selected operators by **Vendor_Only**. The selection is retained in the generated job for retries.
