# Administration

Admin centralises global configuration and active-workspace maintenance. The available actions depend on the signed-in role.

## Roles

- `admin`: manage permitted users, templates, accessible workspaces and authorised portability operations.
- `super-admin`: full role/access control, configuration and Full Environment portability, plus incoming transfer approval.

Safeguards prevent removal, deactivation or demotion of the last active administrator.

## Create user and Users

Administrators can:

- create accounts;
- rename users;
- change or reset passwords;
- enable or disable accounts;
- assign permitted roles;
- manage workspace access where authorised;
- delete eligible accounts.

Leave a password field empty when an edit should preserve the current password.

## Report Templates Management

Templates belong to the active workspace and are stored below `data/workspaces/<workspace>/slides-templates/`. Their metadata is stored in that workspace's `report_templates` table.

Available actions:

- New
- Import CSV
- Edit
- Rename
- Duplicate
- Change NSA/SA type
- Set Default
- Export
- Delete

One template can be default for each technology within a workspace. Reporting initially selects that default but does not change it when a user chooses another template for one job. New workspaces start without templates.

## Report Template Editor

**Edit** opens the selected template in a large dialog. The template selector and duplicate Admin heading are intentionally omitted from the embedded editor.

### Grid behaviour

- The table scrolls vertically and horizontally inside its viewport.
- The bottom action bar remains visible.
- Shared slide cells are visually merged across charts on the same slide.
- Row controls add, remove, reorder and preview chart definitions.
- Edited cells use a light pastel-yellow background.
- Newly inserted text is highlighted more strongly.
- A successful save resets all change highlighting.

### Validation

- Manual cell edits are validated immediately.
- Filter errors identify `Slide: n - Chart: n`.
- Fixing the invalid cell clears the error message.
- Filter conditions render on separate lines with visual bullets; bullets are not stored in the cell.
- CSV filter cells retain one condition per line.

### Assistance and previews

- Searchable single-select assistance for layouts, chart types, fields and positions.
- Ordered multi-select assistance for Rows, Columns and Legend.
- Shared Filter Builder with parsed-expression display.
- Chart Data Preview opens the full filtered dataset directly.
- Chart Preview reuses the shared Interactive Preview.
- **Update Template** applies preview values to the in-memory row; it does not save to disk.

## Import / Export / Transfer

### Export targets

- Config
- Report Templates from the active workspace
- Auto-calculated Fields from the active workspace
- An accessible workspace
- Full Environment with selected workspaces

Admins can export/transfer the active workspace's Report Templates and Auto-calculated Fields, plus workspaces they can access. Super-admins can also include global configuration and Full Environment content. Template and field packages preselect a destination workspace with the same name as their source, where available, and allow more destinations to be selected.

Exports run as disk-backed jobs and show estimated progress. The ZIP download starts when package creation finishes.

### Import workflow

1. Select a Dashboard Analytic ZIP.
2. Wait for upload progress.
3. Review detected content and overwrite warnings.
4. Confirm import.
5. Follow processing progress.

Workspace replacement is automatic: the application closes the target when required, imports the replacement, and removes obsolete old files only after success.

### Transfer to other server

1. Choose **Content to export/transfer**.
2. Enter destination URL/IP and port; the default port is `7278`.
3. Press Enter or select **Connect and request approval**.
4. A destination super-admin accepts or rejects the offer.
5. Follow export creation and transmission at source.
6. Follow reception and automatic import at destination.

The dialog remembers the last destination. Active state is restored after page reload, resumable reception tolerates temporary connection cuts and contacting can be cancelled.

Complete unimported packages appear in **Recovered transfer packages** with content, workspaces, creation time, size, Import and Delete actions. Incomplete remnants are removed automatically.

## Database Management

Database Management has two clearly separated subsections: **Backup Protection** and **Database Viewer**.

### Backup Protection

**Admin → Database Management → Backup Protection** separates **On demand backup** from **Scheduled backups**. On demand backup contains side-by-side **Backup** and **Restore** panels.

In **Backup**, select one or more content types:

- **Configuration Content: Application database** stores the shared application configuration.
- **Workspace Content: Workspace Database** stores the selected workspace SQLite databases.
- **Workspace Content: Report Templates** stores one CSV file for each Report Template.
- **Workspace Content: Auto-calculated Fields** stores one JSON file containing every selected workspace definition.
- **Workspace Content: Input** stores raw dataset files when explicitly selected.
- **Workspace Content: Output** stores generated reports and Chart Sets when explicitly selected.

Application database, Workspace Database, Report Templates and Auto-calculated Fields are selected by default. Input and Output are opt-in. Selecting any workspace content reveals **Workspaces to include**, containing only workspaces you can access. Report Template CSV files use `workspaces/<workspace name>/report-templates/` in Backup and Export ZIPs; this portable path is independent from the application's internal workspace folder name. Use **Backup folder** and **Browse** to choose the server-visible destination, then use **Backup Now** to create a ZIP in the background from the current content and workspace selection. Content, workspace and folder selections are saved for the scheduler without enabling it; the job appears in the floating background-task card and keeps the Admin panel in place.

In **Restore**, choose a server-visible **Backup folder** and one of its ZIP files. The application reads the selected backup's manifest to detect its granular content and affected workspace names, with a structural fallback for older ZIPs, then shows a structured overwrite confirmation grouped into **Configuration Content** and **Workspace Content**. Choose the individual parts to restore only after reviewing that existing data will be replaced. Restore work also runs in the floating background-task card. The ZIP selector refreshes after an immediate backup and periodically while Admin remains open, so completed scheduled backups appear without a page reload.

Enable the schedule to select hourly, daily, weekly or monthly execution. Weekly schedules expose a weekday selector and monthly schedules expose a day-of-month selector.

Set **Retention backups** to keep a maximum number of ZIPs; the scheduler removes the oldest successful backups after creating a newer one. The default storage directory is `data/scheduled-backups`. **Browse** opens a server-side directory picker limited to the application `data` tree, so it reflects directories visible to the host or Docker container rather than the browser's computer. It can create a folder before selecting it.

The status line reports the stored backup count and size, the most recent successful backup and the next scheduled run. Scheduled backups use the same chosen content and workspace selection as the Backup panel. Select Input and/or Output when raw datasets, reports or Chart Sets must be included. Scheduled backups complement infrastructure backups and portable Export packages.

### Database Viewer

**Database Viewer** covers Application and Workspace Databases. It exposes global application-configuration tables, the active workspace database and the materialised combined CDR tables used to accelerate reporting; it is therefore broader than the active workspace alone.

Tables are grouped by ownership:

- **Config Tables**: global application configuration.
- **Workspace Tables**: templates registry, datasets, profiles, logs and unified generated jobs.
- **Individual dataset rows**: one materialised table per dataset.
- **Combined CDR rows**: reporting acceleration tables by CDR type.

The single **Generated jobs** table contains Report and Chart Set rows, distinguished by `job_type`.

The **Report Templates** table is the active workspace's `report_templates` table. It stores each template name, technology, default flag, timestamps and CSV content. Existing CSV templates are migrated automatically when their workspace is opened; compatibility CSV copies are generated only for portable packages.

Capabilities:

- server-side pagination;
- Excel-style distinct-value filters;
- active-filter chips;
- row editing and deletion;
- orphaned materialisation cleanup.

Database edits affect the active workspace immediately. Use Export first when changing production data manually.

## Datasets Management

- Review dataset ID, filename, kind, status and ownership.
- Rename datasets.
- Use Workspace for processing, preview and deletion actions.

Datasets Management appears below Database Management in Admin.

## App Logs

App Logs is a separate tab but supports administration and incident analysis.

- User filtering is case-insensitive.
- Usernames display in lowercase.
- **Executed by** distinguishes user steps from `system` steps.
- Login events include success/failure details.
- Only meaningful actions are recorded, not every click.

## Operational checklist

1. Replace bootstrap passwords.
2. Review workspace access periodically.
3. Back up configuration and data roots.
4. Test restoration with a non-production package.
5. Review App Logs after failures or permission changes.
6. Avoid manual Database Management edits unless the impact is understood.
