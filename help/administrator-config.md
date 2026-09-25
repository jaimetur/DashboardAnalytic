# Administrator Config

Administrator Config centralises user, portability, database and dataset administration. Application-wide runtime settings are in Application Config; workspace-owned templates and chart mappings are on the separate Workspace Config page. Available actions depend on the signed-in role. Only visible for `admin` and `super-admin` roles.

## Roles

- `user-viewer`: use permitted workspace features and App Logs; cannot open Application Config or Workspace Config.
- `user-editor`: edit Application Config and the active workspace's Workspace Config panels; cannot use user-management controls.
- `admin`: manage users within policy, edit Application Config and Workspace Config, manage datasets, and export/import/transfer content for accessible workspaces.
- `super-admin`: create or modify super-admin accounts, assign workspace access, edit Application Config and Workspace Config, export Full Environments, and approve incoming server transfers.

An admin cannot modify a super-admin account or assign the super-admin role. The signed-in account cannot delete itself, and at least one active super-admin must remain.

**Application Config** is the application-wide runtime settings page and is available to `user-editor`, `admin` and `super-admin`. **Workspace Config** is a separate workspace-scoped page with Report Templates Management, Operator Mappings and Vendor Mappings. Both require an active session; Workspace Config operations also require an open workspace. See [Application Config](app-config.md) and [Workspace Config](workspace-config.md) for the respective workflows.

## Create user and Users

Administrators can:

- create accounts;
- rename users;
- change or reset passwords;
- enable or disable accounts;
- assign permitted roles;
- manage workspace access where authorised;
- delete eligible accounts.

Only a super-admin can change workspace access. Leave a password field empty when an edit should preserve the current password. **Reset password** restores `super123`, `admin123` or `demo123` for the three bootstrap names and uses `Ericsson123` for another account; the dialog displays the resulting password so it can be changed or communicated securely.

## Import / Export / Transfer

### Export targets

- Application Config
- Dashboards from the active workspace
- Report Templates from the active workspace
- Operator/Vendor Mappings & Colors from the active workspace
- Auto-calculated Fields from the active workspace
- An accessible workspace
- Full Environment with selected workspaces

Admins can export/transfer the active workspace's Dashboards, Report Templates, Operator/Vendor Mappings & Colors and Auto-calculated Fields, plus complete workspaces they can access. Super-admins can also export Application Config and a Full Environment. Dashboard, template, mapping and field packages preselect a destination workspace with the same name as their source, where available, and allow one or more accessible destinations to be selected.

Importing or transferring Report Templates synchronizes the destination library with the package. Templates absent from the package are removed unless a saved local Dashboard uses them. A template used by a local Dashboard keeps its local definition when the package contains a matching name; names are matched without case differences, so the import does not create a second copy. When the same package also includes Dashboards, its Report Templates replace the destination library because the Dashboard definitions are replaced too. Selective backup restore uses the same rule.

A Full Environment always contains Application Config and the complete database/input content, Dashboard definitions, Report Templates, Operator/Vendor Mappings & Colors and Auto-calculated Fields for every selected workspace. Selecting Full Environment only chooses the package type; the workspace picker opens when **Export ZIP** or **Transfer to other server** is pressed. **Include generated Reports, Chart Sets and Dashboard PPT jobs** controls whether their `output/` trees are included. At least one workspace is required.

Exports run as disk-backed jobs and show estimated progress. The ZIP download starts when package creation finishes.

### Import workflow

1. Select a Dashboard Analytic ZIP and wait for its disk-backed upload.
2. Review the manifest-detected content, affected workspaces and overwrite warnings.
3. For Dashboard, Report Template, Operator/Vendor Mappings & Colors or Auto-calculated Field packages, choose one or more accessible destination workspaces; a matching source name is preselected when available.
4. Confirm import.
5. Follow the background import in the floating task card.

Workspace replacement is automatic: the application closes the target when required, imports the replacement, and removes obsolete old files only after success.

### Transfer to other server

1. Choose **Content to export/transfer**.
2. Enter destination URL/IP and port; the default port is `7278`.
3. Press Enter or select **Connect and request approval**.
4. A destination super-admin accepts or rejects the offer.
5. Follow export creation and transmission at source.
6. Follow reception and automatic import at destination.

The dialog remembers the last destination. Active state is restored after page reload, resumable reception tolerates temporary connection cuts and contacting can be cancelled.

Literal private IP destinations such as `192.168.1.17` are contacted directly, bypassing proxy variables inherited by Docker. The receiving application must listen on `0.0.0.0` rather than only `127.0.0.1`, and its host firewall must allow inbound TCP traffic on the selected port. When the destination is the Docker host itself, use `host.docker.internal`; a different computer on the LAN should use that computer's LAN IP.

For super-admins, complete unimported packages appear in **Recovered transfer packages** with content, workspaces, creation time, size, Import and Delete actions. Incomplete remnants are removed automatically.

## Database Management

Database Management has two clearly separated subsections: **Backup Protection** and **Database Viewer**.

### Backup Protection

**Admin → Database Management → Backup Protection** separates **On demand backup** from **Scheduled backups**. On demand backup contains side-by-side **Backup** and **Restore** panels.

In **Backup**, select one or more content types:

- **Configuration Content: Application database** stores the shared application configuration.
- **Workspace Content: Workspace Database** stores the selected workspace SQLite databases.
- **Workspace Content: Dashboards** stores one JSON file with every Dashboard definition and its comments for each selected workspace.
- **Workspace Content: Report Templates** stores one CSV file for each Report Template.
- **Workspace Content: Operator/Vendor Mappings & Colors** stores one JSON file containing every canonical Operator and Vendor, alias, row position and thematic colour.
- **Workspace Content: Auto-calculated Fields** stores one JSON file containing every selected workspace definition.
- **Workspace Content: Input** stores raw dataset files when explicitly selected.
- **Workspace Content: Output** stores generated Reports, Chart Sets and Dashboard PowerPoint jobs when explicitly selected.

Application database, Workspace Database, Dashboards, Report Templates, Operator/Vendor Mappings & Colors and Auto-calculated Fields are selected by default. Input and Output are opt-in. Selecting any workspace content reveals **Workspaces to include**, containing only workspaces you can access. Dashboard, template and mapping JSON/CSV files use dedicated paths below `workspaces/<workspace name>/` in Backup and Export ZIPs; these portable paths are independent from the application's internal workspace folder name. Use **Backup folder** and **Browse** to choose the server-visible destination, then use **Backup Now** to create a ZIP in the background from the current content and workspace selection. Content, workspace and folder selections are saved for the scheduler without enabling it; the job appears in the floating background-task card and keeps the Admin panel in place.

In **Restore**, choose a server-visible **Backup folder** and one of its ZIP files. The application reads the selected backup's manifest to detect its granular content and affected workspace names, with a structural fallback for older ZIPs, then shows a structured overwrite confirmation grouped into **Configuration Content** and **Workspace Content**. Choose the individual parts to restore only after reviewing that existing data will be replaced. Restore work also runs in the floating background-task card. The ZIP selector refreshes after an immediate backup and periodically while Admin remains open, so completed scheduled backups appear without a page reload.

Enable the schedule to select hourly, daily, weekly or monthly execution. Weekly schedules expose a weekday selector and monthly schedules expose a day-of-month selector.

Set **Retention backups** to keep a maximum number of ZIPs; the scheduler removes the oldest successful backups after creating a newer one. The default storage directory is `APP_DATA_DIR/scheduled-backups`. **Browse** opens a server-side directory picker limited to `APP_DATA_DIR`, so it reflects directories visible to the host or Docker container rather than the browser's computer. It can create a folder before selecting it.

The status line reports the stored backup count and size, the most recent successful backup and the next scheduled run. Scheduled backups use the same chosen content and workspace selection as the Backup panel. Select Input and/or Output when raw datasets, Reports, Chart Sets or Dashboard PPT jobs must be included. Scheduled backups complement infrastructure backups and portable Export packages.

### Database Viewer

**Database Viewer** covers Application and Workspace Databases. It exposes global application-configuration tables, the active workspace database and the materialised combined CDR tables used to accelerate reporting; it is therefore broader than the active workspace alone.

Tables are grouped by ownership:

- **Config Tables**: global application configuration.
- **Workspace Tables**: templates, datasets, profiles, logs, workspace state, Dashboard selections, Dashboard selected rows, Dashboard PPT jobs and unified classic generated jobs.
- **Individual dataset rows**: one materialised table per dataset.
- **Combined CDR rows**: reporting acceleration tables by CDR type.

The **Generated jobs** table contains Report and Chart Set rows, distinguished by `job_type`. Dashboard PowerPoint history is stored separately in **Dashboard PPT jobs** because each row retains its Dashboard definition and applied filter snapshot.

The **Report Templates** table is the active workspace's `report_templates` table. It stores each template name, technology, default flag, timestamps and CSV content. Existing CSV templates are migrated automatically when their workspace is opened; compatibility CSV copies are generated only for portable packages.

#### Operator Mappings and Vendor Mappings tables

In Admin's Database Viewer, **Operator Mappings** (`operator_mappings`) and **Vendor Mappings** (`vendor_mappings`) are workspace database tables. Each stores a `source_value` and its `canonical_value`. One row maps the canonical label to itself; additional rows map source aliases to that label. These tables explain why different source spellings appear as one Operator or Vendor in charts. Alias lookup is case-insensitive, and one source label cannot belong to two canonical groups of the same type.

The related **Chart mapping groups** table (`chart_mapping_groups`) stores each group's `mapping_type`, `canonical_value`, `position` and `color`. Its position establishes the explicit chart order: Operator order also drives Subscriber dimensions, while Vendor order drives Vendor dimensions and the Vendor part of `Operator_Vendor`. The `#RRGGBB` colour provides a stable chart theme; related shades distinguish multiple campaigns or series. Neither alias mapping nor chart order rewrites source workbooks, individual CDR rows or combined CDR tables.

Select either mapping table in Database Viewer to inspect its rows, paginate 100 at a time, filter distinct values from a column, review active filter chips, edit a non-key cell or delete one row. `source_value` is a primary key and cannot be edited there; use Workspace Config to add or change an alias. In **Chart mapping groups**, `mapping_type` and `canonical_value` identify the group, while `position` and `color` hold its order and colour. Direct edits to these related tables are individual row operations and can leave a group's aliases, identity or order inconsistent.

Use [Workspace Config → Operator Mappings](workspace-config.md#operator-mappings) or [Vendor Mappings](workspace-config.md#vendor-mappings) for group operations: add a canonical identity, edit its aliases or colour, Save, Move up/down, and confirm Delete. A canonical rename also updates exact references in Report Templates and saved Dashboards, and group changes clear chart caches. Database Viewer supports inspection, filtering and individual row edits or deletion, but a row-level change there does not perform the group-level rename and ordering workflow. Use the Workspace Config controls when changing a mapping group so aliases, order and colour stay consistent. Admin's export, transfer and backup workflows carry both mapping types together as **Operator/Vendor Mappings & Colors**.

Capabilities:

- 100-row server-side pagination with First/Previous/Next/Last;
- Excel-style distinct-value filters;
- active-filter chips;
- row editing and deletion;
- orphaned materialisation cleanup.

Saving or deleting a row clears analysis caches so later Dashboard and Reporting requests use the new value. Database edits affect the active workspace immediately. Use Export first when changing production data manually.

## Datasets Management

- Review dataset ID, editable name, stored path, uploader, upload time and last update.
- Rename a dataset inline; queued and processing rows remain locked until their current work finishes.
- Preview any Ready dataset in a separate tab.
- Open Ready Data, Voice or Speech CDRs in Datasets Analysis.
- Apply available VFUK/3UK mappings to an eligible CDR or clear its persisted Vendor mapping.
- Delete a dataset after confirmation whenever it is not processing; stop active processing from Workspace first.

## Operational checklist

1. Replace bootstrap passwords.
2. Review workspace access periodically.
3. Back up configuration and data roots.
4. Test restoration with a non-production package.
5. Review App Logs after failures or permission changes.
6. Avoid manual Database Management edits unless the impact is understood.
