# E2E Dashboards

E2E Dashboards combines processed CDRs into interactive, template-driven Dashboards. Each template Slide becomes one dashboard, displaying all its charts together.

## Manage Dashboards

1. Enter a **Dashboard name** and select a workspace **Template**. Both NSA and SA template libraries are available.
2. Click **Create**. All available processed CDRs are initially selected; refine the selection before interpreting results.
3. Use **Save** to retain the current name, template, sources and filters in the active workspace database.
4. Use **Open** to restore a saved dashboard, **Duplicate** to create an independent copy, or **Close** to leave the current dashboard.
5. **Delete** removes only the selected definition after confirmation.
6. **Export** downloads a versioned JSON definition; **Import** restores one with a new identity. The JSON contains template and dataset references and filters, not source data or chart images. Import into a workspace with the corresponding template and dataset IDs, or adjust its source selections before viewing.

Dashboard definitions belong to the workspace and are included when its database is backed up, exported or duplicated. They do not create Reporting jobs or PowerPoint files. The last open dashboard is restored when returning to this tab in the same browser session. Changes are retained when **Save** is pressed; unsaved changes trigger a warning before leaving or opening another dashboard.

## Adaptative Filters

The left subpanel contains **CDR Data**, **CDR Voice**, **CDR Speech**, **Scope**, and the date bounds. Ctrl/Cmd-click selects multiple source files. Multivendor Comparison requires vendor mappings for every selected source. NR Mode and Template are selected when the Dashboard is created.

The right subpanel exposes available Market, Operator, Vendor, Region, City, Session Type, Technology and RAT columns. **Date from** and **Date to** use the source timestamp; the end date includes its entire day. Sources without a usable date column contribute no rows when a date range is active.

The right side separates built-in **Default Filters** from Dashboard-specific **Additional Filters**. Additional filters use a pastel-pink panel and controls so they remain visually distinct. Each categorical filter supports searching values, **All**, **None**, and individual checkboxes. All removes that restriction; None intentionally selects zero rows. Available values adapt to the other active filters. Selected values remain visible even if the current combination has no matches. A source without an actively filtered column contributes no rows instead of silently ignoring that restriction.

Each filter has a circular **×** action. Confirming it removes an added filter or hides a default filter from the Dashboard; hidden default filters can be restored with **Select field to add new filter**.

### Additional Filters

Open **Select field to add new filter** and use its in-menu search box to find any column available in the selected CDRs, including workspace Auto-calculated Fields, then click **Add Filter**. The picker has the same width and dropdown behaviour as the filter fields. Its choices come from materialized values in the selected combined datasets, including the current geographic and date scope. The field is loaded only when it is added, so Dashboard preparation stays compact.

For example, define `7-cities` for CDR-Data with `Yes` when City belongs to the comparison group and `No` otherwise. Add the field as a filter and select only `Yes`. Every dashboard chart using CDR-Data then receives only those matching samples, followed by its own template filters. Removing a custom filter removes its restriction.

## Shared data and refresh

The application queries the existing combined CDR tables directly, extending their columns from the selected processed datasets only when necessary. Opening a Dashboard compiles its datasets, dates, NR Mode and adaptive filters into SQL. Facets sharing the same predicate are aggregated in a single table scan. Small selections of up to 25,000 rows are persisted as indexed `(dataset_id, source_row_id)` keys; larger selections retain the same SQL predicate without duplicating or inserting large key sets before the viewer becomes available. Facet values and row counts are persisted with the selection, so reopening an unchanged Dashboard after an application restart avoids repeating those scans.

Each visible chart joins its materialized selection to the relevant combined CDR table, or applies the stored SQL predicate for a large selection, and reads only its KPI, grouping and template-filter columns. pandas receives this reduced result for the calculations and rendering that still require it. Generated PNGs are stored in `<workspace database directory>/.dashboard-chart-cache` and reused across sessions, with a bounded 200-image LRU policy.

Dashboard selections are implementation caches, not workspace datasets: `dashboard_filter_selections` stores their filter metadata, facets and row counts, while `dashboard_filter_selection_rows` stores the compact `(dataset_kind, dataset_id, source_row_id)` references when the selection is at most 25,000 rows. These tables intentionally do not appear in the Datasets list or the Database Viewer, which expose user datasets and the three combined CDR tables only.

A filter change selects a new consistent SQL snapshot for every dashboard in the template. Requests are debounced and obsolete responses are ignored. Navigating to another dashboard uses that same selection. **Refresh Data** (or **Refresh** inside the viewer) checks backing data and template edits. Session tokens and chart DataFrames remain bounded in memory and may expire; persistent SQL selections and PNGs remain reusable until their data, filters or template definition changes or the LRU policy removes them.

NR Mode follows Reporting semantics: Voice and Speech are classified by NSA/SA, while valid Data attempts are retained even when their sample RAT records a fallback. Use Technology or RAT filters for explicit sample-level restrictions.

## View Dashboard

Click **View Dashboard** after preparation completes. The viewer occupies 96% of the desktop viewport width and expands on small screens.

- **Previous**, **Next**, and the dashboard selector navigate template Slides in numeric order.
- Charts retain their order and relative placeholder positions from the selected Layout in `Template_CDR_analysis.pptx`. Title and Transition slides appear as section dashboards. Small screens stack charts for readability.
- **View Dataset** appears over a chart on hover or keyboard focus, remains visible for two seconds after the pointer leaves, and is always available on touch devices. It opens the chart's filtered samples, with pagination and a full **Download CSV** action.
- **Edit Template**, available to administrators, opens the workspace template editor at the first row of the current dashboard. Closing the editor refreshes the dashboard definition.
- **Manage Auto-calculated Fields**, available to administrators, uses the shared workspace field manager. Refresh data after a materialization job finishes if the viewer was left open.
- **Adaptative Filters** moves the same filter panel into a floating dialog. The fixed and floating views share the same controls and state; edits update every dashboard without closing the viewer. Closing this dialog returns the controls to the main tab.
- Escape closes the active dashboard dialog; keyboard focus returns to its invoking control.

Missing sources, invalid templates and render errors are displayed instead of being mistaken for successful charts. Check source selections, filtered row counts and template fields, then use **Refresh Data**.
