# E2E Dashboards

E2E Dashboards is the main template-driven analysis workspace. It combines processed Data, Voice and Speech CDRs, applies one synchronized selection to a complete Dashboard and renders every template slide interactively before producing a PowerPoint.

Each Dashboard stores its name, NR mode, Report Template, adaptive and additional filters, hidden filters, slide comments and, when requested, its Dataset Universe in the active workspace. Scope, selected CDRs and dates can be applied temporarily or saved independently from filters. A Dashboard does not copy source datasets or generated cache files.

## Before creating a Dashboard

1. Open a workspace and process the required CDR-Data, CDR-Voice or CDR-Speech datasets.
2. Persist Vendor mappings before using Multivendor Comparison.
3. Create or import an NSA/SA Report Template in Workspace Config.
4. Open E2E Dashboards. Any user with workspace access can manage Dashboard definitions; `user-editor`, `admin` and `super-admin` can open Edit Template and Auto-Calculated Fields from the Dashboard viewer and expanded chart viewer.

Dashboard uses the same Report Template schema and renderer as Reporting. This guide covers how the template is selected and used by a Dashboard. For template columns, structural slides, supported chart types, recipes, template filters, aggregations, legends, layouts and colours, see [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

## Manage Dashboards

1. Enter **Dashboard name**, select **NR Mode** and choose a compatible **Template**.
2. Click **Create Dashboard**. The definition is persisted immediately and opens in Dashboard Datasets & Filters.
3. Use Open to restore a Dashboard in the editor or the green eye to enter View Dashboard directly.
4. Edit a name in the table and save it with the green check. The **NR Mode** and **Template** columns also provide selectors for changing an existing Dashboard. Confirming either change invalidates its prepared reports and charts, then rebuilds them from the new compatible template while preserving its saved Scope, CDR universe, date range, adaptive filters, custom fields and comments.
5. Duplicate creates an independent definition. Close leaves the active definition without deleting it.
6. Delete removes the definition after confirmation; it does not remove CDRs, templates or generated PPT jobs.

**Export Dashboard** creates the versioned ZIP accepted by Admin Import. **Import Dashboard** also accepts the legacy standalone JSON definition. Imported definitions need a compatible template; saved universes retain their dataset identifiers, while legacy definitions without one start from the newest ready CDRs in the destination workspace.

The last open Dashboard and page scroll position are remembered in the browser session. The main Dashboard Filters panel starts collapsed for every new authenticated session; opening or closing it is remembered across reloads and module navigation only while that same authenticated session remains active. Real unsaved filter or Dataset Universe changes require Save, Discard or Cancel before navigation. Logging out clears the temporary open-Dashboard, scroll, preview and universe state. Management-only name, NR Mode and Template inputs do not create false unsaved-filter warnings.

## Dashboard Datasets & Filters

The panel separates the comparison scope and selected universe under **Select Dataset Universe** from the default and additional filters under **Select Dataset Filters**. Each column has its own Apply and Save actions and its own unapplied/unsaved badges. PPT and View actions appear on the following row.

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

- **Apply Universe** applies changed Scope, CDRs and dates without changing the saved Dashboard universe.
- **Save Universe** stores and applies the current Scope, CDR and date selection.
- **Reload** restores the saved Scope, CDR and dates without altering filters.
- **Apply Filters** applies changed filters without changing the Dashboard defaults.
- **Save Filters** applies and persists adaptive filters, additional fields and hidden filters.
- **Clear Filters** removes adaptive-filter restrictions without changing the Dataset Universe.
- **Reload Saved Filters** restores only the persisted filters and keeps the current Scope, CDRs and dates.

Returning to an already prepared combination restores its snapshot and charts without recalculation. Filter-value and dataset order do not create different cache entries for equivalent selections.

If View Dashboard or Generate PPT is requested with unapplied adaptive-filter changes, the dialog provides Apply, Discard, Save or Cancel. Pending universe changes are prepared before continuing and can be persisted beforehand with **Save Universe**.

- **Apply Filters and Continue** applies, waits for preparation and continues.
- **Discard and Continue** restores the last applied selection and continues.
- **Save and Continue** saves, prepares and continues.
- **Cancel** takes no action.

## Preparation lifecycle and cache

Combined CDR tables are both the source of record and the direct SQL source for filters, chart datasets and chart rendering. Dashboard selection records retain compact counts, facets and reproducible predicates; they do not copy rows into a separate projection database.

Preparation is debounced and stale responses are ignored. A new foreground request replaces the current one; an equivalent cached request restores immediately. Without opening each Dashboard, the library prepares four reusable universes sequentially in the background: every ready CDR of each type, the newest CDR, the two newest CDRs, and the newest plus the third-newest CDR. All four use automatic `Oldest` and `Newest` dates and retain the Dashboard's saved filters, template and comparison scope. A foreground open takes priority over this low-priority work and can reuse any universe that has already finished.

Manage Dashboards shows `Preparing n/4` until all four background universes are reusable, then changes to Ready. **Open Filters** and **View Dashboard** remain available during that preparation; opening one cancels or yields the low-priority warm-up as needed and gives the requested Dashboard priority. The floating background-task card appears only for an explicit open, refresh or export request. Foreground dataset preparation reports percentage progress through source-column, universe-selection and slide phases. Canvas models are generated only when their chart is viewed, refreshed or included in a requested PPT job. Queued and running user-requested tasks provide an **Interrupt task** action. View Dashboard opens immediately and centres a yellow **Preparing Dashboard dataset** card until the requested slides replace it.

`.dashboard-data-cache` stores reusable preview manifests, Canvas chart models and legacy PIL artifacts; it no longer contains `dashboard-analytics.sqlite3` or copied CDR projections. Cache keys include dataset revisions, selection, scope and renderer version. Opening a workspace removes artifacts from older application/cache versions while retaining current ones. Workspace Clear cache cancels active user-requested work and removes derived cache only; definitions, combined CDRs, templates and generated jobs remain intact. Nothing is automatically rebuilt after clearing it.

## View Dashboard

Use View Dashboard or the library eye action. Opening the viewer from the library does not expand the main Dashboard Filters panel. **Dashboard Filters** opens those controls in a floating panel without the redundant View Dashboard and Generate PPT actions. A centered preparation card remains until updated slides and charts are ready. The viewer uses approximately 96% of the viewport and preserves the template's 16:9 layout.

After the visible slide finishes loading, the browser silently caches the remaining slides by proximity: next, previous, two ahead, two behind, and so on. Opening an individual chart switches this behaviour to the chart sequence using the same alternating order. Moving to another position restarts the sequence around it, and closing the viewer stops scheduling further work. These requests reuse the normal Canvas-model cache and do not appear in the floating background-task card.

### Slides and navigation

- Select any template slide or use the enlarged First, Previous, Next and Last controls, which match the individual chart viewer. Every action in the upper row combines text with its SVG icon at a consistent size: the orange Generate PPT action appears immediately before the red Refresh Dashboard action that closes the row. Presentation is the first button in the navigation row and a spaced vertical divider separates it from First.
- Left/Right Arrow navigates outside editable controls.
- Title and Transition slides use branded Dashboard Analytic typography.
- Chart rows preserve template order and placeholder geometry.
- Layouts ending in `Comments right` place comments beside charts; other layouts place them below.

### Live and expanded chart controls

Hover or focus a chart to reveal Dataset, Expand, Refresh, Zoom and its Chart Definition tab. They hide shortly after pointer exit and remain accessible on touch devices. The tab opens the same editor used in expanded view for that chart; Apply changes the current preview, while Update Template saves the definition to its Report Template row.

- Zoom from 100% to 400% with `−`, `+` and `1:1` reset.
- At 100%, drag a rectangle over the plot to zoom into it; drag a zoomed chart to pan.
- Double-click or use Expand to open the focused chart.
- View Dashboard and its expanded viewer stay above background-task cards and share Reporting's red Close control. The expanded viewer follows Reporting's full-screen card layout, with a descriptive header and an inset chart canvas, while retaining the purple Dashboard palette and floating Chart Definition panel. Both live and expanded charts show boundary-aware left, right, up and down arrows whenever zoom is active; these move the Canvas camera and disable at their respective limits. The expanded viewer's purple First/Previous/Next/Last controls use the same icons and spacing as Reporting. On compact screens, the viewer reduces its header and combines playback and navigation controls into one row. Landscape also places Dashboard selection and actions on one row, while portrait compacts editing actions, fits every navigation button and expands the proportionally positioned chart composition through all remaining viewport height instead of stacking oversized charts or leaving unused space. The collapsible Comments drawer remains fixed to the visible bottom edge in landscape, including the device safe area, independently of overflowing slide content.
- Dashboard Filters remain available in expanded view. Auto-Calculated Fields and Edit Template are also available there for `user-editor`, `admin` and `super-admin`.
- Edit Template focuses the exact template row for the chart. Saving refreshes the Dashboard; closing unchanged retains the current preparation.

For the complete definition of a chart row, see [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

### Filtered Chart Dataset

Dataset opens the exact rows after Dashboard filters and that chart's template filters. It uses server-side 100-row pages with First/Previous/Next/Last and full CSV download.

Every column provides an Excel-style value filter across the complete chart dataset. Active columns are highlighted, value choices remain faceted by other column filters, pagination and CSV retain the selection, and the footer shows filtered rows against total chart rows with **Clear N filters** and Close.

### Comments, Presentation and floating tools

- Add, edit or remove slide comments; Enter or leaving an edit saves immediately.
- **Presentation** supports 3, 5, 10 or 15 seconds with Fade, Slide or no transition. Presentation mode keeps separate floating Pause/Resume and Stop controls available. Manual navigation stops it. On compact landscape screens, its settings dialog stays within the visible viewport and scrolls vertically while keeping its header and actions accessible.
- **Dashboard Filters** moves the same panel into a floating dialog; edits refresh visible charts without automatically saving defaults. View Dashboard and Generate PPT are omitted because the parent viewer already provides those actions.
- **Auto-Calculated Fields** opens the shared workspace manager for `user-editor`, `admin` and `super-admin`.
- Backdrop/Escape closes unchanged dialogs and returns focus. Unsaved Filters, Template Editor or calculated-field changes request a decision first.

## Generate PPT

Generate PPT appears immediately before View Dashboard in the dataset/filter actions and immediately before Refresh Dashboard in the viewer's upper action row. It uses the exact prepared CDRs, dates, scope and applied filters, even if they have not been saved as Dashboard defaults.

The job renders the template into `Template_CDR_analysis.pptx`, preserving slides, layouts, chart placeholder proportions, titles, legends and saved comments. It writes the PPT plus chart PNG, tooltip and Canvas-model assets under `output/dashboards`. Folder and PPT names begin with `yyyymmdd_HHMMSS`; selected Regions and Cities precede the scope and Dashboard name. When every available Region or City is selected, the corresponding name segment is `All Regions` or `All Cities`.

Template authoring details for the exported presentation are centralized in [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

## PowerPoint Generation Jobs

Jobs continue on the server after leaving the page. The table records ID, creator, local date/time, NR Mode, Dashboard, scope, filter snapshot, slides, charts, status and elapsed progress.

Depending on state, actions download the PPT, open/download charts, stop work, retry/relaunch or delete the job and files. The filter action groups CDRs as Data, Voice and Speech and shows exact dates and adaptive filters in a tooltip or dialog. Excel-style header filters search every job column. Administrators can use **Delete All PPTs**.

## Charts Panel

Charts Panel browses completed Dashboard PPT charts. Filter by NR Mode, Dashboard, Template and Scope, then choose a PowerPoint Job. The selector identifies local date/time, Dashboard and scope; header badges repeat Dashboard, date and scope. Polling automatically selects and loads the newest matching job as soon as it finishes.

Cards fill equal template frames and repaint stored Canvas models with the current renderer. Legacy jobs without models retain their PNG. Open any card in the same expanded viewer and Filtered Chart Dataset used by the live Dashboard.

Historical previews retain the job's exact template and selection. **View Filters** opens that snapshot. `user-editor`, `admin` and `super-admin` can open the generating template and Auto-calculated Fields. Dashboard Filters are hidden because a completed export is immutable.

## Portability and maintenance

Dashboard export uses a versioned ZIP accepted by Admin Import. It contains the definition and comments, but excludes source CDRs and caches. Dashboard is an independent Admin export/import/transfer/backup/restore component. Full Workspace and Full Environment include definitions from every selected workspace, with Dashboards listed immediately after Application Config.

## Troubleshooting

- **View Dashboard or Generate PPT is disabled**: inspect the status badge and floating preparation task.
- **A filter has no values**: verify its field/aliases exist and other filters leave matching rows.
- **A chart says that no CDR dataset is selected**: select at least one CDR of the type required by that chart. The chart remains intentionally empty when its source type is absent from the Dataset Universe.
- **A chart is empty**: compare Dataset Universe, Filtered Universe and chart rows; then check NR Mode and the template row in Administrator Config.
- **Multivendor is unavailable**: persist Vendor mapping for every selected CDR.
- **Preparation is failed or remains queued**: inspect App Logs, retry and clear only the workspace Dashboard cache if derived data is invalid.
