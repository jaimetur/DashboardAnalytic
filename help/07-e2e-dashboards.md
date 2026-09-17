# E2E Dashboards

E2E Dashboards is the main template-driven analysis workspace. It combines processed Data, Voice and Speech CDRs, applies one synchronized selection to a complete Dashboard and renders every template slide interactively before producing a PowerPoint.

Each Dashboard stores its name, NR mode, Report Template, adaptive and additional filters, hidden filters and slide comments in the active workspace. Scope, selected CDRs and dates form the temporary Dataset Universe and are rebuilt when the Dashboard opens; they are not persisted in the Dashboard definition. A Dashboard does not copy source datasets or generated cache files.

## Before creating a Dashboard

1. Open a workspace and process the required CDR-Data, CDR-Voice or CDR-Speech datasets.
2. Persist Vendor mappings before using Multivendor Comparison.
3. Create or import an NSA/SA Report Template in Admin.
4. Open E2E Dashboards. Any user with workspace access can manage Dashboard definitions; Template Editor and Auto-calculated Field management require administrator access.

Dashboard uses the same Report Template schema and renderer as Reporting. This guide covers how the template is selected and used by a Dashboard. For template columns, structural slides, supported chart types, recipes, template filters, aggregations, legends, layouts and colours, see [Administration → Report Template reference](10-administration.md#report-template-reference).

## Manage Dashboards

1. Enter **Dashboard name**, select **NR Mode** and choose a compatible **Template**.
2. Click **Create Dashboard**. The definition is persisted immediately and opens in Dashboard Datasets & Filters.
3. Use Open to restore a Dashboard in the editor or the green eye to enter View Dashboard directly.
4. Edit a name in the table and save it with the green check.
5. Duplicate creates an independent definition. Close leaves the active definition without deleting it.
6. Delete removes the definition after confirmation; it does not remove CDRs, templates or generated PPT jobs.

**Export Dashboard** creates the versioned ZIP accepted by Admin Import. **Import Dashboard** also accepts the legacy standalone JSON definition. Imported definitions need a compatible template; their temporary Dataset Universe is rebuilt from ready CDRs in the destination workspace when they are opened.

The last open Dashboard and page scroll position are remembered in the browser session. Real unsaved filter changes require Save, Discard or Cancel before navigation. Management-only name, NR Mode and Template inputs do not create false unsaved-filter warnings.

## Dashboard Datasets & Filters

The panel separates the comparison scope and selected universe under **Select Dataset Universe** from the default and additional filters under **Select Dataset Filters**. **Unapplied filters** and **Unsaved filters** apply only to the filters on the right; changing Scope, CDRs or dates can require preparation but never produces those badges or enables Apply Filters/Save Filters.

### Dashboard Scope

- **Operator Comparison** uses normalized Operator values.
- **Multivendor Comparison** requires Vendor mapping for every selected CDR and expands Operator into its operator/vendor hierarchy.
- Changing comparison scope immediately rebuilds the Dataset Universe without a confirmation dialog. Multivendor selects the newest CDR of each type; Operator Comparison selects the two newest CDRs of each type, or every available CDR when fewer than two exist.

NR Mode follows the shared reporting rule: Voice and Speech sessions are classified as NSA/SA; valid Data attempts remain available even when a sample RAT records a fallback. RAT can be restricted explicitly with the adaptive filter.

### Dataset Universe and dates

Select one or more CDR Data, Voice and Speech sources. Date from/Date to default to `Oldest` and `Newest`. Their small in-field **Use oldest** and **Use newest** actions restore those symbolic values, while the textboxes show the currently resolved bounds as `Oldest (YYYY-MM-DD)` and `Newest (YYYY-MM-DD)`. Every preparation resolves them from the selected CDRs. Selecting a calendar day uses and displays a fixed date for the current session. Date to includes the complete day, and calendar month navigation does not change the selection until a day is chosen.

The ready summary distinguishes:

- **Dataset Universe**: rows contributed by the selected CDR sources; without date or adaptive-filter restrictions, the ready summary reuses the effective Dashboard count so it matches Filtered Universe;
- **Filtered Universe**: rows remaining after dates and adaptive filters;
- chart rows: the subset after the selected template row's own filters.

### Default filters and aliases

Default filters appear in this order: `Market`, `Operator`, `Vendor`, `Region`, `City`, `Campaign`, `RAT`, `Session Type`, `Call Status`. Technology is not an adaptive Dashboard filter because NR Mode is selected on the Dashboard definition.

| Visible filter | Supported columns in priority order |
| --- | --- |
| Region | `Region` → `G_Level_2` → `G Level 2` |
| City | `City` → `G_Level_4` → `G Level 4` |
| Campaign | `Campaign` → `campaign` |
| RAT | `RAT_A` → `RAT` → `Sample_RAT_A` |
| Call Status | `Call_Status` → `call_status` → `status` |

Aliases resolve per row: an empty higher-priority value falls back to the next column. Hover or keyboard-focus an aliased filter to see its complete priority list.

Each multiselect provides search, **All**, **None** and individual values. All removes the restriction; None deliberately produces zero rows. Menus stay open while values are selected and close after pointer exit. Choices normally come from persisted dataset profiles; missing fields are read from combined CDR tables.

### Additional Filters

**Select field to add new filter** searches all columns available in the selected CDRs and all applicable workspace Auto-calculated Fields. Adding a field loads its values in a separate request that respects the current CDRs, dates and other filters without preparing the complete Dashboard.

The circular `×` removes an additional filter or hides a default filter after confirmation. A hidden default can be restored from the field picker. Auto-calculated Fields apply only to their declared CDR types and are materialized into the corresponding combined CDR table when first needed.

### Apply, Save, Clear and Reload

- **Apply Filters** applies changed filters without changing the Dashboard defaults. It remains disabled for changes limited to Scope, CDRs or dates.
- **Save Filters** applies and persists adaptive filters, additional fields and hidden filters.
- **Clear Filters** removes adaptive-filter restrictions without changing the Dataset Universe.
- **Reload Saved Filters** restores only the persisted filters and keeps the current Scope, CDRs and dates.

Returning to an already prepared combination restores its snapshot and charts without recalculation. Filter-value and dataset order do not create different cache entries for equivalent selections.

If View Dashboard or Generate PPT is requested with unapplied adaptive-filter changes, the dialog provides these actions. Pending changes limited to Scope, CDRs or dates prepare the temporary Dataset Universe automatically before continuing.

- **Apply Filters and Continue** applies, waits for preparation and continues.
- **Discard and Continue** restores the last applied selection and continues.
- **Save and Continue** saves, prepares and continues.
- **Cancel** takes no action.

## Preparation lifecycle and cache

Combined CDR tables are both the source of record and the direct SQL source for filters, chart datasets and chart rendering. Dashboard selection records retain compact counts, facets and reproducible predicates; they do not copy rows into a separate projection database.

Preparation is debounced and stale responses are ignored. A new request replaces the current one; an equivalent cached request restores immediately. A global gate allows only one explicitly requested Dashboard dataset-preparation phase to run at a time. Listing or saving Dashboards, changing workspace, editing a template and clearing cache do not prepare other Dashboards in the background.

Manage Dashboards reports whether a reusable prepared selection is Ready or must be opened to prepare. The floating background-task card appears only for an explicit open, refresh or export request. Dataset preparation reports percentage progress through source-column, universe-selection and slide phases. Canvas models are generated only when their chart is viewed, refreshed or included in a requested PPT job. Queued and running user-requested tasks provide an **Interrupt task** action. View Dashboard opens immediately after a universe change and centres a yellow **Preparing Dashboard dataset** card until the updated slides replace it.

`.dashboard-data-cache` stores reusable preview manifests, Canvas chart models and legacy PIL artifacts; it no longer contains `dashboard-analytics.sqlite3` or copied CDR projections. Cache keys include dataset revisions, selection, scope and renderer version. Opening a workspace removes artifacts from older application/cache versions while retaining current ones. Workspace Clear cache cancels active user-requested work and removes derived cache only; definitions, combined CDRs, templates and generated jobs remain intact. Nothing is automatically rebuilt after clearing it.

## View Dashboard

Use View Dashboard or the library eye action. View Dashboard remains available from the floating Adaptative Filters panel; after resolving changes it closes that panel and returns to the viewer. A centered preparation card remains until updated slides and charts are ready. The viewer uses approximately 96% of the viewport and preserves the template's 16:9 layout.

After the visible slide finishes loading, the browser silently caches the remaining slides by proximity: next, previous, two ahead, two behind, and so on. Opening an individual chart switches this behaviour to the chart sequence using the same alternating order. Moving to another position restarts the sequence around it, and closing the viewer stops scheduling further work. These requests reuse the normal Canvas-model cache and do not appear in the floating background-task card.

### Slides and navigation

- Select any template slide or use the enlarged First, Previous, Next and Last controls, which match the individual chart viewer. Presentation, Refresh and Generate PPT are kept in a separate action group, in that order.
- Left/Right Arrow navigates outside editable controls.
- Title and Transition slides use branded Dashboard Analytic typography.
- Chart rows preserve template order and placeholder geometry.
- Layouts ending in `Comments right` place comments beside charts; other layouts place them below.

### Live and expanded chart controls

Hover or focus a chart to reveal Dataset, Expand, Refresh and Zoom controls. They hide shortly after pointer exit and remain accessible on touch devices.

- Zoom from 100% to 400% with `−`, `+` and `1:1` reset.
- At 100%, drag a rectangle over the plot to zoom into it; drag a zoomed chart to pan.
- Double-click or use Expand to open the focused chart.
- View Dashboard and its expanded viewer stay above background-task cards and share Reporting's red Close control. The expanded viewer follows Reporting's full-screen card layout, with a descriptive header and an inset chart canvas, while retaining the purple Dashboard palette and floating Chart Definition panel. Both live and expanded charts show boundary-aware left, right, up and down arrows whenever zoom is active; these move the Canvas camera and disable at their respective limits. The expanded viewer's purple First/Previous/Next/Last controls use the same icons and spacing as Reporting.
- Adaptative Filters, Auto-calculated Fields and Edit Template remain available in expanded view when permitted.
- Edit Template focuses the exact template row for the chart. Saving refreshes the Dashboard; closing unchanged retains the current preparation.

For the complete definition of a chart row, see [Administration → Report Template reference](10-administration.md#report-template-reference).

### Filtered Chart Dataset

Dataset opens the exact rows after Dashboard filters and that chart's template filters. It uses server-side 100-row pages with First/Previous/Next/Last and full CSV download.

Every column provides an Excel-style value filter across the complete chart dataset. Active columns are highlighted, value choices remain faceted by other column filters, pagination and CSV retain the selection, and the footer shows filtered rows against total chart rows with **Clear N filters** and Close.

### Comments, Presentation and floating tools

- Add, edit or remove slide comments; Enter or leaving an edit saves immediately.
- **Presentation** supports 3, 5, 10 or 15 seconds with Fade, Slide or no transition. Manual navigation stops it.
- **Adaptative Filters** moves the same panel into a floating dialog; edits refresh visible charts without automatically saving defaults.
- **Auto-Calculated Fields** opens the shared workspace manager for administrators.
- Backdrop/Escape closes unchanged dialogs and returns focus. Unsaved Filters, Template Editor or calculated-field changes request a decision first.

## Generate PPT

Generate PPT appears immediately before View Dashboard in the dataset/filter actions and after Presentation in the viewer. It uses the exact prepared CDRs, dates, scope and applied filters, even if they have not been saved as Dashboard defaults.

The job renders the template into `Template_CDR_analysis.pptx`, preserving slides, layouts, chart placeholder proportions, titles, legends and saved comments. It writes the PPT plus chart PNG, tooltip and Canvas-model assets under `output/dashboards`. Folder and PPT names begin with `yyyymmdd_HHMMSS - Dashboard Name`.

Template authoring details for the exported presentation are centralized in [Administration → Report Template reference](10-administration.md#report-template-reference).

## PowerPoint Generation Jobs

Jobs continue on the server after leaving the page. The table records ID, creator, local date/time, NR Mode, Dashboard, scope, filter snapshot, slides, charts, status and elapsed progress.

Depending on state, actions download the PPT, open/download charts, stop work, retry/relaunch or delete the job and files. The filter action groups CDRs as Data, Voice and Speech and shows exact dates and adaptive filters in a tooltip or dialog. Excel-style header filters search every job column. Administrators can use **Delete All PPTs**.

## Charts Panel

Charts Panel browses completed Dashboard PPT charts. Filter by NR Mode, Dashboard, Template and Scope, then choose a PowerPoint Job. The selector identifies local date/time, Dashboard and scope; header badges repeat Dashboard, date and scope. Polling automatically selects and loads the newest matching job as soon as it finishes.

Cards fill equal template frames and repaint stored Canvas models with the current renderer. Legacy jobs without models retain their PNG. Open any card in the same expanded viewer and Filtered Chart Dataset used by the live Dashboard.

Historical previews retain the job's exact template and selection. **View Filters** opens that snapshot. Administrators can open the generating template and Auto-calculated Fields. Adaptative Filters are hidden because a completed export is immutable.

## Portability and maintenance

Dashboard export uses a versioned ZIP accepted by Admin Import. It contains the definition and comments, but excludes source CDRs and caches. Dashboard is an independent Admin export/import/transfer/backup/restore component. Full Workspace and Full Environment include definitions from every selected workspace, with Dashboards listed immediately after App Config.

## Troubleshooting

- **View Dashboard or Generate PPT is disabled**: inspect the status badge and floating preparation task.
- **A filter has no values**: verify its field/aliases exist and other filters leave matching rows.
- **A chart says that no CDR dataset is selected**: select at least one CDR of the type required by that chart. The chart remains intentionally empty when its source type is absent from the Dataset Universe.
- **A chart is empty**: compare Dataset Universe, Filtered Universe and chart rows; then check NR Mode and the template row in Administration.
- **Multivendor is unavailable**: persist Vendor mapping for every selected CDR.
- **Preparation is failed or remains queued**: inspect App Logs, retry and clear only the workspace Dashboard cache if derived data is invalid.
