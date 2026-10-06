# Non-Qualified Calls

Non-Qualified Calls brings the CDR Drive Test follow-up into Dashboard Analytic: an executive summary of every call and test that did not complete, a drill-down table of those calls, and a shared follow-up of each one with a status, a responsible team, an assignee and a comment thread that every user of the workspace sees.

The module is in development, so its main tab shows a red **NEW** label. It is hidden from every user until an admin or super-admin activates it in [Admin → Features Activation](administrator-config.md).

## Which calls are Non-Qualified

A Non-Qualified (NQ) call is any Voice or Speech call, or any Data test, whose result is not **Completed**: for example **Failed** and **Dropped** Voice calls and **Failed** and **Cutoff** Data tests. The result is read from the processed `status` field of the CDR, or from `Call_Status`, `Test_Result` or `Test_Status` when it is missing. Rows without a result are not included.

Every ready Voice, Speech and Data CDR of the active workspace is indexed automatically the first time the page opens and again whenever a CDR is added, reprocessed or deleted, so the list always matches the workspace datasets. The top of the **Filters** panel shows how many NQ calls and CDRs are indexed and when they were last indexed; **Refresh** reloads them. **Export PowerPoint** and **Export Word**, on the right of the indexing badge and Refresh, download the Executive Summary and the Progress Status of the filtered calls with the look of the page (indicator cards, breakdowns, donuts, timeline, age and workload, and the detail tables), the report selection on the cover (with the period chosen in the Progress View), the same document as the Reporting artifact; a progress dialog stays open while it is prepared.

Each call keeps a stable identity built from its service, Operator, Campaign and test or session identifier (`Test_ID`, `Session_ID_A`, `Session_id` or `JOIN_ID`; without one, its subscriber, test name and start and end times). Its status, team, assignee and comments therefore stay with it when its CDR is reprocessed or uploaded again. When the same call appears in two CDRs, it is listed once.

## Filters

The **Filters** panel restricts the summary, the table and the Excel export together:

- **CDRs**, **Campaign**, **Operator**, **Operator_Vendor**, **Vendor**, **Region**, **Cluster**, **City**, **Service**, **Technology**, **Test Name**, **Result**, **Failure Classification** and **Failure Category**, from the indexed calls. **Operator_Vendor** is the `<Operator>_<Vendor>` identity and **Vendor** the vendor alone; **City** offers the workspace **Main Cities** first.
- **Status**, **Team** and **Assignee**, from the follow-up. **Unassigned** selects calls without a team or assignee.
- **Search** finds text in the call fields (Operator, Vendor, Campaign, Region, City, Technology, test, result, failure fields and cell) and in the comments.
- **Open calls only**, **Assigned to me** and **Without comments**.

Selecting every value of a filter, or none, applies no restriction. Active filters appear as chips above the table; click a chip to remove it. **Reset Filters** clears them all.

The selection is shared: it is saved in the workspace, so every user finds the last filters applied, in any session and on any device. **Assigned to me** always refers to the user viewing the page.

## Summary

The **Summary** panel is the executive view of the filtered calls: the number of Non-Qualified Calls, how many are open and closed, and how many have a responsible team or comments. Breakdowns by Service, Result, Status, Team, Failure Classification, Operator, Vendor, Region, Cluster, City and, last, by CDR show where the calls concentrate; the By CDR card is wider and shows each CDR name in full.

Click any bar to drill down: the table shows only that value. Click the same bar again to remove that filter.

## Progress View

The **Progress View** below the Summary shows how the follow-up advances for the filtered calls:

- Indicators: calls, open and closed calls, calls attended (with a follow-up change or a comment), commented, with a team and assigned, and the average days to close.
- Donut charts **By Status**, **By Team**, **By Assignee**, **By Service** and **By Result**; each legend shows the full name with its count and share; hovering a slice shows its value, count and share, and a click on a slice or a legend entry filters the calls by that value.
- A timeline per **week**, **month**, **quarter** or **year** of the calls detected, attended, commented, closed and reopened (hover a period to read all its values), with a table that adds the status changes, the open backlog at the end of each period and the average days to close.
- The age of the open calls, the workload of each team and assignee (open, closed and total calls) and the recent activity.

## Calls

The **Calls** table lists one row per call with its service, start time, Operator and Vendor, City and Campaign, test and technology, result and failure classification and category (hover a failure to read its subcategory and comment), followed by its follow-up and comments. Click a column header to sort by it; the table is paginated with 25, 50, 100 or 200 rows per page.

Users with the `user-editor`, `admin` or `super-admin` role change the **Status**, **Team** and **Assignee** directly in the row; each value keeps the colour of its status or team. The Comments column shows how many comments a call has and its latest comment; click it to read the thread or add a comment. `user-viewer` accounts see the same information read-only.

Select several rows with their checkboxes, or every row of the page with the header checkbox, to set the status, team or assignee of all of them at once.

**Export Excel** downloads every call that matches the filters, not only the current page, in three sheets: **NQ Calls** with the call fields and their follow-up, **Comments** with every comment and its author, edits and deletion, and **History** with every follow-up change.

## Call details and activity

Click a row to open its details beside the table. The header shows the service, result, Operator, Campaign, time and place of the call, followed by its status, team and assignee and who changed them last.

**Activity** is a timeline of the call: comments with their author and time, and every change of status, team or assignee with the previous and new values. Write in the comment box and press **Add Comment** or Ctrl+Enter to share a comment with every user of the workspace. Comments keep line breaks and accept up to 5000 characters.

Authors can edit and delete their own comments, and admins and super-admins can edit or delete any comment. Edited comments show **edited**; deleted comments leave a note with who deleted them and when, and the history keeps the previous text of every edited or deleted comment.

**Call Details** lists the main fields of the call, its location (opened in OpenStreetMap) and its CDR, followed by every non-empty field of the original CDR row, which you can filter by name or value.

When another user changes a call after you loaded it, your change is refused and the list reloads, so nobody overwrites a newer follow-up by mistake. The open page refreshes the calls and the open call every minute.

## Statuses and teams

**Statuses & Teams** (for `user-editor` accounts and above) configures the values shared by the workspace. Each status and team has a name, a colour and a position; statuses marked **Closed** count as closed in the summary and are left out by **Open calls only**. The first status is shown for calls nobody has followed up yet.

The defaults are the statuses Open, Under Investigation, Pending Information, Resolved (closed) and Not Applicable (closed), and the teams RAN Optimisation, Core Network, IMS / VoLTE, Transport and Device & Test Setup. Renaming a status or team updates every call that uses it. A status or team that is still used by a call cannot be removed; move its calls first.

**Workspace Config → Non-Qualified Calls Teams** edits the teams with their colours and **members**: choose the workspace users that belong to each team; a user can belong to several teams. When a call has a team with members, its **Assignee** list offers only them, and moving the call to a team its assignee does not belong to clears the assignee. A team without members accepts every user of the workspace.

## Reporting Jobs

Reporting Jobs include a **Non-Qualified Calls** artifact with the Executive Summary and the Progress Status of the calls in PowerPoint, Word and/or Excel. Each job chooses its own filters (the same as the Filters panel), the period of the progress timeline and whether to include only open calls. See [Reporting](reporting.md).

## Storage and portability

The module stores its data in the workspace database, visible in [Admin → Database Management](administrator-config.md):

| Table | Content |
| --- | --- |
| NQ Calls | The indexed NQ rows of every CDR (rebuilt automatically). |
| NQ Call Sources | Which CDR revision each indexed CDR comes from. |
| NQ Call Tracking | The status, team, assignee and version of each followed-up call. |
| NQ Call Comments | Every comment with its author, time, edits and deletion. |
| NQ Call History | Every change of status, team or assignee and every comment edit or deletion. |
| NQ Call Options | The configured statuses and teams. |
| NQ Team Members | The users that belong to each team. |

The follow-up — statuses, teams with their members, tracking, comments and history — travels as **NQ Call Tracking** with Admin → Import / Export / Transfer, Full Workspace and Full Environment packages, workspace transfers, and backups and restores. Imports merge it into the destination workspace: missing statuses and teams are added, a call's newer follow-up replaces an older one, and comments and history entries are added once, so importing the same package again changes nothing. The follow-up applies to the destination calls with the same identity, so import the same CDRs there to see it.
