# Administration

Admin centralises shared configuration and active-workspace maintenance. The available actions depend on the signed-in role.

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

## Slides Templates Management

Templates are shared across workspaces and stored below `config/slides-templates/`.

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

One template can be default for each technology. Reporting initially selects that default but does not change it when a user chooses another template for one job.

## Slides Template Editor

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

## Export / Import

### Export targets

- Config
- Slides Templates
- Config + Slides Templates
- An accessible workspace
- Full Environment with selected workspaces

Admins can export/transfer Slides Templates and workspaces they can access. Super-admins can also include global configuration and Full Environment content.

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

Tables are grouped by ownership:

- **Config Tables**: global application configuration.
- **Workspace Tables**: datasets, profiles, logs and unified generated jobs.
- **Individual dataset rows**: one materialised table per dataset.
- **Combined CDR rows**: reporting acceleration tables by CDR type.

The single **Generated jobs** table contains Report and Chart Set rows, distinguished by `job_type`.

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
