# Administration

The Administration area is for authorised users who manage access and operational traceability. It is separate from the normal Workspace and reporting workflow.

## User management

Administrators can create accounts, change a username or role, replace a password, enable or disable an account, and delete accounts where permitted. Safeguards prevent the last active administrator from being removed, deactivated or demoted. Use individual accounts rather than sharing the initial administrator credentials, and remove access when it is no longer needed.

The **Users** table is the authoritative operational view: submit the row action after editing its username, password, role or active state. Leave a password field empty when its current password should be retained. The red action buttons across this area identify access-management changes.

## Dataset oversight

The Administration view also exposes the datasets recorded by Workspace. Use it to verify the source filename, assigned input type, processing state and ownership when investigating a missing Dashboard or Reporting input. Dataset analysis itself remains in the normal Workspace and Dashboard workflow; the Admin view is for oversight and traceability.

## PowerPoint slide catalogue importer

The **Slide catalogue importer** accepts a separate UTF-8 CSV for **NSA** and **SA**. The active files are stored under `assets/ppt-slides-catalog/` and can be exported from the matching Admin panel before editing. The required columns are `Slide`, `Slide tittle`, `Slide Subtittle`, `CDR source`, `KPI`, `Chart type`, `Filters` and `Grouping`; each row that has a CDR source represents one chart image. `Slide tittle` and `Slide Subtittle` are taken from the supplied PowerPoint templates; a non-empty subtitle is rendered beneath the title. Where the source header has multiple lines, the exported CSV uses the literal `\n` sequence, which the importer restores as a line break. Validate edits in the exported CSV, then import it into the matching technology panel.

The imported catalogue becomes the active reference for subsequent reports. For every automated slide, the renderer counts its CDR rows and uses the matching PowerPoint master layout: one row uses the one-column image placeholder, two rows use two image placeholders, and so on through four columns. The existing analyst commentary area is retained and cleared. The importer also rewrites the NSA/SA Slide Catalogue tables in the PowerPoint Reporting help page from the active catalogues. The audit log records each successful import.

## Audit activity

The audit view records significant application actions, including account changes, uploads, processing actions and report generation. Use it to investigate an unexpected upload, report generation or configuration-related operation. Record the time window, account and affected dataset or report before escalating an issue.

## Operational checklist

1. Change the initial administrator password after deployment.
2. Review user access periodically.
3. Confirm that persistent directories and the database are backed up according to the environment policy.
4. Check audit records after an operational incident.
5. Never use the administration screen to expose customer CDR contents outside the approved workflow.
