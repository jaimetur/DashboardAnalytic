# Administration

The Administration area is for authorised users who manage access and operational traceability. It is separate from the normal Workspace and reporting workflow.

## User management

Administrators can create accounts, change a username or role, replace a password, enable or disable an account, and delete accounts where permitted. Safeguards prevent the last active administrator from being removed, deactivated or demoted. Use individual accounts rather than sharing the initial administrator credentials, and remove access when it is no longer needed.

The **Users** table is the authoritative operational view: submit the row action after editing its username, password, role or active state. Leave a password field empty when its current password should be retained. The red action buttons across this area identify access-management changes.

## Dataset oversight

The Administration view also exposes the datasets recorded by Workspace. Use it to verify the source filename, assigned input type, processing state and ownership when investigating a missing Dashboard or Reporting input. Dataset analysis itself remains in the normal Workspace and Dashboard workflow; the Admin view is for oversight and traceability.

## Slide Catalogue Management

**Slide Catalogue Management** maintains named NSA and SA report definitions stored under `assets/ppt-slides-catalog/`. The workspace list shows the catalogue name, technology and current default. It supports **Set Default**, **Delete**, **Duplicate** and **Export**; changing a name saves it automatically. The default catalogue is preselected in Reporting, while a user can still select another compatible catalogue for a single report run.

Import a UTF-8 CSV by giving it a name and selecting the target NSA or SA section. The current schema is `Slide`, `Slide tittle`, `Slide Subtittle`, `Layout`, `Chart Tittle`, `CDR source`, `KPI`, `Chart type`, `Legend`, `Filters`, `Grouping_Rows` and `Grouping_Columns`. Each distinct slide number creates a new slide from the named template layout; each CDR-source row represents one chart image. `Title Slide` and `Transition Slide` create structural slides and leave all KPI/chart fields empty. If an older compatible schema is supplied, the application asks in a floating dialog whether it should convert it. Conversion maps compatible headings, splits a former `Grouping` hierarchy into rows and columns, assigns missing layouts and migrates former preserve rows into structural slides. Validation failures are shown in a floating dialog and are also recorded in the audit log.

## Slide Catalogue Editor

Choose a stored catalogue in the editor picker, then select **Edit**. The editable grid has horizontal and vertical scrolling. Every cell can be typed manually; selecting a cell also opens contextual assistance:

- **Layout**, **CDR source**, **KPI** and **Chart type** offer single, searchable selections.
- A fixed first column keeps the **↑**, **↓**, **+** and **−** row controls visible while scrolling. **+** creates a new unsaved sibling row with the same slide title/subtitle and layout, ready for another chart definition; the arrows change row order (and therefore the placeholder order for charts in the same slide), while **−** removes the row until the catalogue is saved. The final remaining row cannot be deleted. **Re-Enumerate Slides** sorts the row blocks by their current slide number and renumbers their distinct slide values consecutively from 1 without changing any other cell content; review the result, then use **Save Catalogue** to persist it.
- **Grouping_Rows**, **Grouping_Columns** and **Legend** offer searchable multi-selection and preserve existing selected values without duplicating dimensions.
- **Filters** opens the Filter Builder. It loads existing conditions, allows adding/removing conditions, and offers CDR fields, operators and values. Conditions are joined with AND. `NOT IN` and `NOT CONTAINS` are supported.

`Layout` must match a named layout in the selected PPT template and provide enough chart placeholders for the number of CDR rows in that slide. The title placeholder receives `Slide tittle` and its optional blue subtitle; the analyst-comments placeholder stays blank. During report generation the renderer removes inherited template chart examples and inserts calculated charts in the selected layout. Imports/default changes also refresh the NSA/SA catalogue tables in the PowerPoint Reporting help page.

## Audit activity

The audit view records significant application actions, including account changes, uploads, processing actions and report generation. Use it to investigate an unexpected upload, report generation or configuration-related operation. Record the time window, account and affected dataset or report before escalating an issue.

## Operational checklist

1. Change the initial administrator password after deployment.
2. Review user access periodically.
3. Confirm that persistent directories and the database are backed up according to the environment policy.
4. Check audit records after an operational incident.
5. Never use the administration screen to expose customer CDR contents outside the approved workflow.
