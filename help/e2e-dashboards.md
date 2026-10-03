# E2E Dashboards

Build an interactive Dashboard from processed Data, Voice and Speech CDRs, using a saved Report Template. Apply one dataset selection to its slides, explore the charts, then export the result to PowerPoint.

> [!NOTE]
> **A Dashboard is a saved definition, not a copy of your data.** It stores its template, filters, comments and optional Dataset Universe. Source CDRs and generated caches remain separate.

## Choose your task

| I want to… | Go to |
| --- | --- |
| Create or change a Dashboard | [Manage Dashboards](#manage-dashboards) |
| Select CDRs, dates and comparison scope | [Dashboard Datasets & Filters](#dashboard-datasets-filters) |
| Understand Apply versus Save | [Apply, Save, Clear and Reload](#apply-save-clear-and-reload) |
| Explore slides and chart data | [View Dashboard](#view-dashboard) |
| Export a presentation | [Generate PPT](#generate-ppt) |
| Review exported jobs or charts | [PPT Generation Jobs](#ppt-generation-jobs) / [Charts Panel](#charts-panel) |
| Resolve empty charts or preparation problems | [Troubleshooting](#troubleshooting) |

## Before creating a Dashboard

1. Open the correct workspace and process the required CDR types.
2. Create or import a compatible **NSA/SA Report Template** in Workspace Config.
3. For Multivendor Comparison, persist Vendor mappings first.
4. Open **E2E Dashboards**.

Any user with workspace access can manage Dashboard definitions. **user-editor**, **admin** and **super-admin** can also open **Edit Template** and **Auto-Calculated Fields** from the viewer.

> [!TIP]
> For a first comparison: create a Dashboard, choose its Scope and CDRs, apply the universe, apply any filters, then open **View Dashboard**. Inspect the charts before generating a PPT.

Dashboards use the same template schema and renderer as Reporting. Detailed template authoring is covered in [Workspace Config → Report Template reference](workspace-config.md#report-template-reference).

## Manage Dashboards

### Create a definition

1. Enter **Dashboard name**.
2. Select **NR Mode** and a compatible **Template**.
3. Click **Create Dashboard**. The saved definition opens in Dashboard Datasets & Filters.

Names are unique within each NR Mode: an NSA and an SA Dashboard may share a name. The library sorts NSA first, then by name.

Workspaces with NSA Report Templates receive once the NSA Dashboard **RF Quality (RSRP & SINR)** and its template **NSA - RF Quality (RSRP & SINR)**, with separate LTE and NR RSRP/SINR CDF, average, distribution, threshold and quality-map slides for Data, Voice and Speech, followed by the NSA NetCheck black-logo closing slide. Each chart family starts with an All CDR types slide pooling valid Data, Voice and Speech observations, followed by the separate types; LTE and NR remain separate. CDF slides use a two-by-two layout with LTE and NR above their contour histograms (5 dB RSRP bins; 1 dB SINR bins). Histograms show percentages per series, match CDF colours and campaign widths, and retain multivendor line patterns; red-to-green background bands match the quality-class slides. NR shares use valid NR measurements and do not measure availability across the entire route. It has no saved Dataset Universe, so it uses the newest NSA CDRs; edit or delete it like any other Dashboard. See [Network Insights](network-insights.md#rf-quality-template-and-dashboard).

### Row actions

| Action | Effect |
| --- | --- |
| **View Dashboard** | Open the interactive slide viewer |
| **Open Filters** | Open the Dashboard's dataset and filter controls |
| **Generate PPT** | Open the export selection dialog |
| **Duplicate** | Create an independent definition |
| **Export Dashboard** | Download a versioned ZIP accepted by Admin Import |
| **Delete** | Remove the definition after confirmation |

**Close** leaves the active definition without deleting it. Deleting a Dashboard does not delete its CDRs, template or generated PPT jobs.

### Change name, NR Mode or template

Edit the name in the table and confirm with the green check. NR Mode and Template have their own selectors.

> [!WARNING]
> **Changing NR Mode or Template invalidates the prepared charts.** The application rebuilds them using the compatible template. An NR Mode change replaces the CDR universe with the newest inputs of the new mode; a template-only change keeps the selected universe.

Saved filters, date settings, custom fields and comments are preserved. Only CDRs of the active NR Mode participate.

### Session and unsaved changes

The browser remembers the last open Dashboard and page position during the authenticated session. The main filter panel starts collapsed for a new session; its open/closed state is remembered while that session remains active.

Leaving with real unsaved filter or universe changes requires **Save**, **Discard** or **Cancel**. Management-only name, NR Mode and Template inputs do not trigger false filter warnings.

Logging out clears temporary open-Dashboard, preview, scroll and universe state. Saved definitions remain in the workspace.

## Dashboard Datasets & Filters

**Open Filters** places this panel below the selected Dashboard row. Opening another Dashboard moves it to that row; **Close Filters** removes it.

In the viewer, **Dashboard Filters** opens the same controls in a floating panel. Small screens also use the floating version when opening filters from the library.

### Two independent selections

| Column | Controls | Saved by |
| --- | --- | --- |
| **Select Dataset Universe** | Scope, CDR sources and dates | Save Universe |
| **Select Dataset Filters** | Default filters, additional fields and hidden filters | Save Filters |

Each column has its own applied/unsaved state. Saving filters does not save the universe, and saving the universe does not replace the saved filters.

### Dashboard Scope

| Scope | Comparison | Initial CDR selection when switching scope |
| --- | --- | --- |
| **Operator Comparison** | Normalized Operator values | Latest two CDRs of each type, or all available when fewer exist |
| **Multivendor Comparison** | Operator/vendor hierarchy | Latest CDR of each type |

Changing Scope here rebuilds the universe immediately. The viewer's Scope control instead asks for confirmation before rendering its charts again.

> [!IMPORTANT]
> **Multivendor requires mapped Vendors.** The workspace must have at least two distinct cached Vendors, and the selected CDRs must satisfy the mapping/comparison requirements. A single-vendor selection cannot produce a Multivendor comparison.

NR Mode follows the shared reporting rule: Voice/Speech sessions are classified as NSA/SA; valid Data attempts remain available even when a sample RAT records a fallback. Use the **RAT** filter for a narrower technology selection.

### Dataset Universe and dates

Select one or more Data, Voice and Speech CDRs. Each selector lists only inputs of the Dashboard's NR Mode, for example **CDR Data (NSA)**. Older saved references to the other NR Mode are not used.

| Date setting | Meaning |
| --- | --- |
| **Oldest** | Resolve the first available date from selected CDRs during preparation |
| **Newest** | Resolve the last available date from selected CDRs during preparation |
| A chosen calendar day | Use that fixed date |

**Use oldest** / **Use newest** restore automatic bounds. The fields display their resolved dates, such as `Oldest (2026-01-01)`. Date to includes the whole selected day. Navigating calendar months does not change the date until you select a day.

> [!TIP]
> Use automatic date bounds when you want newly selected CDRs included without manually adjusting dates. Use fixed dates for a reproducible time window.

### Read the row counts

| Count | What it represents |
| --- | --- |
| **Dataset Universe** | Rows contributed by the selected CDR sources |
| **Filtered Universe** | Rows remaining after dates and Dashboard filters |
| **Chart rows** | Rows remaining after that chart's template filters as well |

Without date or adaptive-filter restrictions, the ready summary reuses the effective Dashboard count so Dataset Universe and Filtered Universe agree.

An empty chart can coexist with a nonempty Filtered Universe: its source type or chart-specific filters may exclude the remaining rows.

### Default filters and aliases

The default order is **Market → Region → City → Campaign → Operator → Vendor → RAT → Session Type → Call Status**. Technology is not an adaptive filter because NR Mode belongs to the definition.

| Visible filter | Source columns in priority order |
| --- | --- |
| Region | `Region` → `G_Level_2` → `G Level 2` |
| City | `City` → `G_Level_4` → `G Level 4` |
| Campaign | `Campaign` → `campaign` |
| RAT | `RAT_A` → `RAT` → `Sample_RAT_A` |
| Call Status | `Call_Status` → `call_status` → `status` |

Aliases resolve per row: an empty higher-priority field falls back to the next column. Hover or keyboard-focus the filter to inspect its aliases.

Each multiselect supports search, individual values and **Select All / None**. **Main Cities** selects the configured workspace cities available in the current CDR selection.

> [!CAUTION]
> **Selecting no values returns no rows.** Selecting all values removes the restriction. This differs from modules where an empty filter means “all”. Use Clear Filters to remove restrictions deliberately.

Selecting every value individually also makes the field unrestricted, even when only one value is available. An unrestricted field includes new values from later-added CDRs automatically and displays **All values**.

Applying or saving a changed universe reloads choices from its CDRs. Menus stay open while selecting and close after pointer exit. Older truncated catalogues are completed from source rows.

### Additional Filters

1. Search **Select field to add new filter**.
2. Choose a CDR column or an applicable workspace Auto-calculated Field.
3. Use **Add Filter**, then select its values.

Values load against the current CDRs, dates and other filters without preparing the whole Dashboard. The circular **×** removes an additional filter or hides a default filter after confirmation; the field picker can restore a hidden default.

Auto-calculated Fields apply to their declared CDR types. They are materialized into the relevant combined CDR table when first needed.

### Apply, Save, Clear and Reload

| Action | Changes the current view | Persists defaults | Leaves unchanged |
| --- | --- | --- | --- |
| **Apply Universe** | Scope, CDRs and dates | No | Saved universe and filters |
| **Save Universe** | Scope, CDRs and dates | Yes, universe | Saved filters |
| **Reload Universe** | Restore saved universe | No | Current filters |
| **Apply Filters** | Current filters | No | Saved filters and universe |
| **Save Filters** | Filters, additional and hidden fields | Yes, filters | Saved universe |
| **Clear Filters** | Remove restrictions | No | Dataset Universe |
| **Reload Saved Filters** | Restore saved filters | No | Current Scope, CDRs and dates |

> [!NOTE]
> **Apply is temporary; Save changes the Dashboard defaults.** You can preview or export an applied selection without saving it. Returning to an equivalent prepared selection reuses its cached charts.

If **View Dashboard** or **Generate PPT** encounters unapplied filter edits, choose:

| Dialog action | Outcome |
| --- | --- |
| **Apply Filters and Continue** | Prepare the edited filters, then continue |
| **Discard and Continue** | Restore the last applied filters, then continue |
| **Save and Continue** | Save, prepare and continue |
| **Cancel** | Leave the operation unchanged |

Pending universe edits are prepared before continuing. Use **Save Universe** first if you also want them persisted.

## Preparation lifecycle and cache

### What happens while preparing?

Preparations run in the background and the browser follows progress. A new foreground request replaces the same user's previous request; stale responses are ignored. An equivalent cached selection restores without recalculation.

The viewer opens immediately with a yellow **Preparing Dashboard dataset** card until its requested slides are ready. User-requested tasks appear in the floating task card and can provide **Interrupt task**.

| Status | Meaning |
| --- | --- |
| **Checking Cache** | Waiting for the server's cache status |
| **Pre-Caching Universe n/m** | Preparing reusable universe n of m |
| **Waiting** | Background pre-caching is queued or paused |
| **Loading data / Rendering** | Foreground preparation is active |
| **Ready** | Reusable universes are prepared |

Open Filters, View Dashboard and PPT export remain available during background pre-caching.

### Background pre-caching

The library can prepare up to five universes: all ready CDRs, and the newest one, two, three and four per type. These use the Dashboard's NR Mode, saved scope/filters/template and automatic dates; duplicate universes are skipped.

Open Dashboards take priority over closed ones. Foreground preparation and PPT export pause this low-priority work, which resumes afterward. An incompatible universe is skipped until the workspace data changes.

> [!TIP]
> You do not need to wait for every background universe to finish. Opening or exporting a Dashboard prepares the requested universe if it is not already reusable.

### What Clear cache removes

Combined CDR tables remain the source for filters and chart data. Selection records keep counts, facets and reproducible predicates; the cache does not copy CDR rows into a separate projection database.

`.dashboard-data-cache` holds derived preview manifests, Canvas models and legacy image artifacts. Its keys include dataset revisions, selection, scope and renderer version. Older-version artifacts are removed when a workspace opens.

> [!WARNING]
> **Workspace Clear cache cancels active user-requested work and removes derived cache only.** It preserves Dashboard definitions, combined CDRs, templates and generated jobs. Nothing rebuilds automatically until requested again.

Canvas models are created when a chart is viewed, refreshed or requested for PPT. After a visible slide loads, nearby slides silently prefetch in the order next, previous, two ahead, two behind. Opening an individual chart uses the chart sequence instead. Closing the viewer stops scheduling further work.

## View Dashboard

Open **View Dashboard** from the library or filter panel. It does not expand the main filters panel automatically; use **Dashboard Filters** for the floating controls.

### Read the header

The viewer preserves the template's 16:9 layout and uses approximately 96% of the viewport. Its header identifies NR Mode, Dashboard and slide position.

- Slide titles and golden-yellow subtitles display in capitals.
- Campaigns, Scope, Regions and Cities identify the applied selection.
- Export snapshots show the selection captured by that PPT job.

Campaign labels are compact, such as **2026-Q2** or **2026-Q2_SA**. Older CDRs may populate cached campaign labels a few seconds after first opening.

### Slides and navigation

| Control | Use |
| --- | --- |
| Slide selector | Jump to a template slide |
| **First / Previous / Next / Last** | Move through slides |
| Left / Right Arrow | Navigate when focus is outside editable controls |
| **Scope** | Switch Operator/Multivendor after confirmation |
| **Dashboard Filters** | Edit the live selection in a floating panel |
| **Generate PPT** | Export the selection |
| **Refresh Dashboard** | Refresh the Dashboard preparation |

Changing Scope renders the charts again and selects the default CDR universe for that scope. Multivendor is unavailable when the workspace has fewer than two Vendors.

Title and Transition slides preserve the template text and branded typography. A title cover shows Campaigns above its decorative divider, with Scope, Regions and Cities beneath it, matching PPT. Chart rows preserve template order and placeholder geometry.

Layouts ending in **Comments right** place comments beside the charts; other layouts place them below. Narrow screens wrap actions and adapt navigation to the available space.

### Live and expanded chart controls

Hover or focus a chart for **Dataset**, **Expand**, **Refresh**, **Zoom** and **Chart Definition**. The controls also remain accessible on touch devices.

| Gesture / action | Result |
| --- | --- |
| **Expand** or double-click | Open the focused chart in the expanded viewer |
| **− / + / 1:1** | Zoom between 100% and 400%, or reset |
| Drag a rectangle at 100% | Zoom into the selected plot area |
| Drag when zoomed | Pan the chart |
| Direction arrows when zoomed | Move the camera; arrows disable at boundaries |

The expanded viewer retains Dashboard filters, chart navigation and a red Close control. Compact portrait/landscape layouts fit navigation and the chart to the viewport; the Comments drawer stays accessible at the bottom.

### Edit a chart definition

The **Chart Definition** tab uses the same editor in live and expanded view:

| Action | Scope |
| --- | --- |
| **Apply** | Change the current preview |
| **Update Template** | Save the definition to the Report Template row |
| **Edit Template** | Focus the exact generating row in the template editor |

Saving the template refreshes the Dashboard. Closing it unchanged preserves the current preparation. Template/calculated-field editing actions require **user-editor**, **admin** or **super-admin**.

> [!IMPORTANT]
> **Updating a Report Template is a saved configuration change.** Use Apply to inspect a temporary preview before committing the chart definition to its template.

The [Report Template reference](workspace-config.md#report-template-reference) describes supported chart types, filters, aggregations, legends and layouts.

### Filtered Chart Dataset

**Dataset** opens rows after both the Dashboard filters and that chart's template filters. It is not the whole Dataset Universe.

The dataset viewer provides:

- Server-side pages of 100 rows, with First/Previous/Next/Last.
- Excel-style value filters across the complete chart dataset.
- A filtered-row count, **Clear N filters** and full CSV download.

Active columns are highlighted. Value choices respond to the other column filters; pagination and CSV retain the same selection.

> [!TIP]
> Open Dataset on an unexpected chart to see exactly which rows contributed. Compare its row count with Filtered Universe before changing the chart formula.

### Comments, Presentation and floating tools

| Tool | Behavior |
| --- | --- |
| Slide comments | Add, edit or remove; Enter or leaving an edit saves immediately |
| **Presentation** | Advance every 3, 5, 10 or 15 seconds, with Fade, Slide or no transition |
| Pause/Resume and Stop | Floating controls remain available in Presentation mode |
| **Dashboard Filters** | Change applied selection without automatically saving defaults |
| **Auto-Calculated Fields** | Open the shared workspace manager for permitted editors |

Manual navigation stops Presentation. Its settings adapt to compact landscape screens. Backdrop/Escape closes unchanged dialogs; pending Filters, Template or calculated-field edits require a decision first.

## Generate PPT

### Choose the export inputs

Open **Generate PPT** from the library, filter panel or viewer. **Select Dashboard Universe and Filters** controls the export's exact selection, which can differ from saved defaults.

| Export subpanel | Settings |
| --- | --- |
| **Dashboard Universe** | Scope, CDR datasets and dates |
| **Main Dashboard Filters** | Operators, Vendors, Regions and Cities |
| **Show All Filters** | Reveal the remaining main filters and Additional Filters |

Only CDRs of the Dashboard's NR Mode are listed. Choices load from the selected CDRs and start with saved filter values, or all available values when unrestricted or no saved values remain available.

**Main Cities** is available for City. Changing CDRs/dates preserves selected values still available; an All selection includes new values. The browser remembers the dialog's last Scope, CDRs and dates per Dashboard/user.

### Save defaults only when intended

| Action | Effect |
| --- | --- |
| **Generate PPT** | Export the dialog's selection |
| **Save Universe** | Also persist its Scope, CDRs and dates in the Dashboard |
| **Save Filters** | Also persist its filter selection |

Save buttons enable when their settings differ from saved defaults. A complete value selection equals an unrestricted field; saved values absent from the selected CDRs are ignored.

> [!IMPORTANT]
> **Export selections take precedence for that job.** You can export applied or dialog-specific filters without saving them as Dashboard defaults. The job's Filters snapshot records what was exported.

If required, the export prepares its selected CDR universe without waiting for library background pre-caching.

### Presentation contents and files

The PPT preserves template slides, layouts, chart proportions, titles, legends and saved comments. Chart subtitles use blue text; Title/Transition subtitles retain the template's yellow accent.

Title covers match the viewer: Campaigns appear in orange above the divider; Scope, Regions and Cities appear beneath in green, cyan and pink. Chart subtitles use normal letter spacing.

Generated PPTs, chart PNGs, tooltips and Canvas assets are stored under **output/dashboards**.

| Filename part | Contents |
| --- | --- |
| Prefix | `yyyymmdd_HHMMSS` |
| Definition | NR Mode, Dashboard name and Scope |
| Geography | Selected Regions joined by ` + `, or All Regions |
| Multiple campaigns | Campaigns joined by `_vs_` at the end |

Operators, Vendors and Cities remain in the job Filters snapshot and are omitted from filenames. Long names are shortened only for filesystem limits.

## PPT Generation Jobs

Jobs continue on the server after you leave the page. The table records ID, creator, local date/time, NR Mode, Dashboard, Scope, filters, slide/chart counts, status and progress.

| Action | Availability / purpose |
| --- | --- |
| **Download PPT** | Download an available completed presentation |
| Chart actions | Open or download generated charts |
| Stop / retry / relaunch | Manage work when the job's state permits |
| Filter action | Inspect sources, dates, campaigns and filters in a tooltip/dialog |
| Delete / **Delete All PPTs** | Remove jobs/files; requires user-editor, admin or super-admin |

Excel-style header filters search job columns. The filter snapshot groups CDRs by Data/Voice/Speech and shows Campaigns above Operators.

> [!NOTE]
> **All Operators / Vendors / Regions / Cities refers to the job's selected CDRs.** Other workspace CDRs do not expand that selection. Saved values absent from those CDRs are not listed.

## Charts Panel

### Find an exported chart

1. Filter by NR Mode, Dashboard, Template, Scope, Region or City.
2. Select a **PowerPoint Job**.
3. Open a chart card in the expanded viewer, or use **View Filters** to inspect the snapshot.

Each filter offers only selections from jobs matching the other active filters. Choices describe complete exported selections. A job with seven cities contributes one City choice containing those seven cities; All Cities/All Regions appears only for jobs exported with those selections.

The job selector identifies its local date/time, NR Mode, Dashboard, Scope and recorded geography. Long lists expose their full values on hover. Polling loads the newest matching completed job.

### Live Dashboard versus saved snapshot

| View | Selection |
| --- | --- |
| **View Dashboard** | Current applied Dashboard inputs |
| **Charts Panel** | The generating PPT job's captured template and inputs |

Stored Canvas models repaint with the current renderer. Legacy jobs without models keep their PNG. The expanded viewer and Filtered Chart Dataset remain available.

> [!IMPORTANT]
> **Completed exports are immutable snapshots.** Dashboard Filters are hidden in Charts Panel. View Filters shows the exported selection; changing a live Dashboard does not rewrite that job.

Permitted editors can open the generating template and Auto-Calculated Fields without changing the saved snapshot.

## Portability and maintenance

**Export Dashboard** creates a versioned ZIP accepted by Admin Import; imports also accept legacy standalone JSON definitions. A compatible destination template is required.

| Included in the definition | Not copied by Dashboard definition export |
| --- | --- |
| Name, NR Mode and template association | Source CDRs |
| Saved filters, hidden/additional fields | Prepared cache files |
| Slide comments | Generated presentation assets |
| Saved Dataset Universe when present | The source rows referenced by its dataset IDs |

Saved universes retain dataset identifiers. Legacy imports without a saved universe start from the destination's newest ready CDRs; check the inputs after import.

Dashboards have their own Admin export/import/transfer/backup/restore component. Full Workspace and Full Environment include definitions from selected workspaces, with Dashboards listed after Application Config.

> [!TIP]
> Verify the template and CDR references after moving a Dashboard to another workspace. Definition portability does not mean its source datasets travelled with it.

## Troubleshooting

| Symptom | Check / action |
| --- | --- |
| View Dashboard or Generate PPT is disabled | Inspect its status badge and explicit preparation task |
| A filter has no choices | Verify source field/aliases and whether other filters leave matching rows |
| Chart says no CDR is selected | Include at least one source CDR of the type that chart needs |
| Filtered Universe is zero | Check dates and empty value selections; use Clear Filters to remove restrictions |
| Chart is empty with nonzero universe | Check its source type, template filters, NR Mode and chart Dataset |
| Multivendor is unavailable | Check at least two Vendors and persist mappings for selected CDRs |
| Preparation failed or stays queued | Inspect App Logs and retry; clear derived Dashboard cache only if invalid |
| Viewer and old export differ | Compare applied live inputs with the completed job's saved snapshot |

> [!WARNING]
> Clear cache is a recovery action for derived artifacts, not a substitute for fixing missing source data, Vendor mappings or an invalid template. Inspect the cause first.
