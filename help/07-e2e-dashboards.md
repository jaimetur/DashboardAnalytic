# E2E Dashboards

E2E Dashboards combines processed CDRs into interactive, template-driven Dashboard Sets. Each template Slide becomes one dashboard, displaying all its charts together.

## Manage Dashboards Set

1. Enter a **Dashboard Set name** and select a workspace **Template**. Both NSA and SA template libraries are available.
2. Click **Create**. All available processed CDRs are initially selected; refine the selection before interpreting results.
3. Use **Save** to retain the current name, template, sources and filters in the active workspace database.
4. Use **Open** to restore a saved set, **Duplicate** to create an independent copy, or **Close Set** to leave the current set.
5. **Delete** removes only the selected definition after confirmation.
6. **Export** downloads a versioned JSON definition; **Import** restores one with a new identity. The JSON contains template and dataset references and filters, not source data or chart images. Import into a workspace with the corresponding template and dataset IDs, or adjust its source selections before viewing.

Dashboard definitions belong to the workspace and are included when its database is backed up, exported or duplicated. They do not create Reporting jobs or PowerPoint files. The last open set is restored when returning to this tab in the same browser session. Changes are retained when **Save** is pressed; unsaved changes trigger a warning before leaving or opening another set.

## Adaptative Filters

The left subpanel contains **CDR Data**, **CDR Voice**, **CDR Speech**, **NR Mode**, **Scope**, and **Template**. Ctrl/Cmd-click selects multiple source files. Multivendor Comparison requires vendor mappings for every selected source.

The right subpanel exposes available Market, Operator, Vendor, Region, City, Session Type, Technology and RAT columns. **Date from** and **Date to** use the source timestamp; the end date includes its entire day. Sources without a usable date column contribute no rows when a date range is active.

Each categorical filter supports searching values, **All**, **None**, and individual checkboxes. All removes that restriction; None intentionally selects zero rows. Available values adapt to the other active filters. Selected values remain visible even if the current combination has no matches. A source without an actively filtered column contributes no rows instead of silently ignoring that restriction.

### Custom Auto-calculated Fields

Choose a workspace field in **Custom Auto-calculated Field** and click **Add Filter**. Its choices come from materialized values in the selected combined datasets, including the current geographic and date scope.

For example, define `7-cities` for CDR-Data with `Yes` when City belongs to the comparison group and `No` otherwise. Add the field as a filter and select only `Yes`. Every dashboard chart using CDR-Data then receives only those matching samples, followed by its own template filters. Removing a custom filter removes its restriction.

## Shared data and refresh

The application reuses the existing combined CDR tables, extending their columns from the selected processed datasets when necessary. It reads the union of their columns, materializes current workspace calculated fields, and applies the dashboard filters without duplicating persistent combined tables. Template chart filters are applied afterwards, using the same chart preparation and rendering engine as Reporting.

A filter change invalidates every dashboard in the set. Requests are debounced and obsolete responses are ignored. The server produces a consistent preview snapshot for all slides; visible charts render on demand and their PNGs are cached. Navigating to another dashboard uses that same filtered snapshot. **Refresh Data** (or **Refresh** inside the viewer) checks backing data and template edits; unchanged source frames are reused. Preview snapshots are bounded in memory and may expire; refreshing recreates them.

NR Mode follows Reporting semantics: Voice and Speech are classified by NSA/SA, while valid Data attempts are retained even when their sample RAT records a fallback. Use Technology or RAT filters for explicit sample-level restrictions.

## View Dashboard Set

Click **View Dashboard Set** after preparation completes. The viewer occupies 80% of the desktop viewport width and expands on small screens.

- **Previous**, **Next**, and the dashboard selector navigate template Slides in numeric order.
- Charts retain their order and relative placeholder positions from the selected Layout in `Template_CDR_analysis.pptx`. Title and Transition slides appear as section dashboards. Small screens stack charts for readability.
- **View Dataset** appears over a chart on hover or keyboard focus, remains visible for two seconds after the pointer leaves, and is always available on touch devices. It opens the chart's filtered samples, with pagination and a full **Download CSV** action.
- **Edit Template**, available to administrators, opens the workspace template editor at the first row of the current dashboard. Closing the editor refreshes the dashboard definition.
- **Manage Auto-calculated Fields**, available to administrators, uses the shared workspace field manager. Refresh data after a materialization job finishes if the viewer was left open.
- **Adaptative Filters** moves the same filter panel into a floating dialog. The fixed and floating views share the same controls and state; edits update every dashboard without closing the viewer. Closing this dialog returns the controls to the main tab.
- Escape closes the active dashboard dialog; keyboard focus returns to its invoking control.

Missing sources, invalid templates and render errors are displayed instead of being mistaken for successful charts. Check source selections, filtered row counts and template fields, then use **Refresh Data**.
