# Non-Qualified Calls

Non-Qualified Calls brings the CDR Drive Test follow-up into DriveTest Analyzer: an executive summary of every call and test that did not complete, a drill-down table of those calls, a shared follow-up of each one with a status, a responsible team, an assignee, a root cause and a comment thread that every user of the workspace sees, and a Root Cause Analysis of where the calls fail.

The module is in development, so its main tab shows a red **NEW** label. It is hidden from every user until an admin or super-admin activates it in [Admin → Features Activation](administrator-config.md).

## Which calls are Non-Qualified

A Non-Qualified (NQ) call is any Voice or Speech call, or any Data test, whose result is not **Completed**: for example **Failed** and **Dropped** Voice calls and **Failed** and **Cutoff** Data tests. The result is read from the processed `status` field of the CDR, or from `Call_Status`, `Test_Result` or `Test_Status` when it is missing. Rows without a result are not included.

Every ready Voice, Speech and Data CDR of the active workspace is indexed automatically the first time the page opens and again whenever a CDR is added, reprocessed or deleted, so the list always matches the workspace datasets. The top of the **Filters** panel shows how many NQ calls and CDRs are indexed and when they were last indexed; **Refresh** reloads them. **Export PowerPoint** and **Export Word**, on the right of the indexing badge and Refresh, download the Executive Summary (its indicators and every breakdown on one slide), the Progress Status and the Root Cause Analysis of the filtered calls with the look of the page (indicator cards, breakdowns, donuts, timeline, age and workload, root domains and causes, Classic vs WhatsApp, and the detail tables), the report selection on the cover (with the period chosen in the Progress View), the same document as the [Reporting](reporting.md) artifact; a progress dialog stays open while it is prepared.

Each call keeps a stable identity built from its service, Operator, Campaign and test or session identifier (`Test_ID`, `Session_ID_A`, `Session_id` or `JOIN_ID`; without one, its subscriber, test name and start and end times). Its status, team, assignee and comments therefore stay with it when its CDR is reprocessed or uploaded again. When the same call appears in two CDRs, it is listed once.

## Filters

The **Filters** panel restricts the summary, the table and the Excel export together:

- **CDRs**, **Campaign**, **Operator**, **Operator_Vendor**, **Vendor_Operator**, **Vendor**, **Region**, **Cluster**, **City**, **Service**, **Technology**, **Test Name**, **Result**, **Failure Classification** and **Failure Category**, from the indexed calls. **Operator_Vendor** is the `<Operator>_<Vendor>` identity, **Vendor_Operator** the same identity as `<Vendor>_<Operator>` (both stay in sync) and **Vendor** the vendor alone; **City** offers the workspace **Main Cities** first.
- **Status**, **Team**, **Assignee**, **Root Domain** and **Root Cause**, from the follow-up. **Unassigned** selects calls without a team or assignee, and **Not classified** calls without a root cause.
- **Search** finds text in the call fields (Operator, Vendor, Campaign, Region, City, Technology, test, result, failure fields and cell) and in the comments.
- **Open calls only**, **Assigned to me** and **Without comments**.

Selecting every value of a filter, or none, applies no restriction. Active filters appear as chips above the table, including those set from the Progress View and the Root Cause Analysis (NR Mode, Call Type, Period, Age of Open Calls, root domain and cause with suggestions, eNB/gNB); click a chip to remove it. **Reset Filters** clears them all.

The selection is shared: it is saved in the workspace, so every user finds the last filters applied, in any session and on any device. **Assigned to me** always refers to the user viewing the page.

## Summary

The **Summary** panel is the executive view of the filtered calls: the number of Non-Qualified Calls, how many are open and closed, how many are attended (followed up with a change or commented), and how many have a responsible team or comments. Breakdowns by Service, Result, Status, Team, Root Domain, Failure Classification, Campaign, Operator, Vendor, Region, Cluster and City show where the calls concentrate, six per row and with the same colours as in the one-slide Executive Summary of the PowerPoint and Word (each status, team and root domain in its colour, the other values in a fixed palette). Campaigns read as everywhere in the tool (*UK_Q2_SA_2026* reads *2026-Q2-SA*; see [Campaign ordering](technical-considerations.md#campaign-ordering)) and still filter by the full campaign.

Click any bar to drill down: the table shows only that value. Click the same bar again to remove that filter.

## Progress View

The **Progress View** below the Summary shows how the follow-up advances for the filtered calls:

- Indicators: calls, open and closed calls, calls attended (with a follow-up change or a comment), commented, with a team and assigned, and the average days to close.
- Donut charts **By Status**, **By Team**, **By Assignee**, **By Service** and **By Result**; each legend shows the full name with its count and share; hovering a slice shows its value, count and share, and a click on a slice or a legend entry filters the calls by that value.
- A timeline per **week**, **month**, **quarter** or **year** of the calls detected, attended, commented, closed and reopened (hover a period to read all its values), with a table that adds the status changes, the open backlog at the end of each period and the average days to close.
- The age of the open calls, the workload of each team and assignee (open, closed and total calls) and the recent activity.

As in the Summary, a click drills down into the calls: a slice or legend entry of a donut, a period of the timeline (in the chart or its table: the calls detected in that period), an age bar (the open calls of that age) or a team or assignee row shows only those calls; click it again to remove that filter. The User Activity table is informative only.

## Root Cause Analysis

The **Root Cause Analysis** panel shows where the filtered calls fail:

- Indicators: the calls, how many have a root cause (**Labelled**), how many are counted with their **Suggested** root cause and how many are **Not classified**. **Count suggested root causes** (on by default) counts the calls without a root cause with the one suggested by their CDR failure classification; turn it off to count only the labelled calls.
- **By Root Domain** and **By Root Cause** bars, in the colour of each domain.
- **Classic vs WhatsApp** (Voice and Speech calls whose test name contains WhatsApp, the other calls, and the Data tests), **NSA vs SA** and **Technology** tables with the calls of each root domain.
- **eNB / gNB with most calls**: the node of the last cell of each call's `Cell_ID` chain (the cell where it ended): identities above 28 bits are NR cells (gNB = NCI / 4096), LTE cells give their eNB (ECI / 256) and smaller identities are 2G/3G cells. The site, host (OSS) and vendor come from the workspace **Vodafone** and **Three** cell mapping datasets when they list the node; otherwise the vendor is the call's.
- A click on a bar, on the first column or the Total of a table, on a cell of a domain, or on an eNB/gNB row shows only those calls (for example the NSA calls of RF), and a second click removes the filter. With **Count suggested root causes** on, the domains and causes include the suggested ones, as the counts do; with it off, only the labelled root causes.

## Calls

The **Calls** table lists one row per call with its start time and service, Operator and Vendor, City and Campaign, test and technology, result with the failure classification and category (hover a failure to read its subcategory and comment), followed by its status, team and assignee, root cause and comments. Related values share a column, one below the other, so the table fits in the panel. Every name of a column header (for example *Service*, *Result*, *Team* or *Assignee*) sorts the table when clicked, and the funnel beside it opens, right below the header, that field's values to filter by them: search them by name, tick them (**Select All / None** ticks or clears the values shown; the causes are grouped under their domain) and **Apply**. A column filter is the same selection as the Filters panel and its chip: the funnel is filled while that field is filtered. Long values are shortened and shown whole when you hover them; on screens narrower than 1600 px the Comments column shows the number of comments and the latest one when you hover it. The table is paginated with 25, 50, 100 or 200 rows per page.

Users with the `user-editor`, `admin` or `super-admin` role change the **Status**, **Team**, **Assignee** and **Root Cause** directly in the row; each value keeps the colour of its status, team or root domain. The Root Domain / Cause column shows the domain above (in its colour) and the cause below. The cause list shows every domain, in its colour, with its causes below it (search them by name; the current cause is ticked): choosing a cause of another domain changes both, and *No cause* keeps the domain alone; a new domain chosen above starts without a cause. While a call has no root cause, the suggested one is shown below the domain and a click on it applies it. Below the status, each row shows when its follow-up last changed and who changed it (hover it for the exact time). The status, team, assignee and root cause lists widen with the window. The **›** button beside the comments opens the call. The Comments column shows how many comments a call has and its latest comment; click it to read the thread or add a comment. `user-viewer` accounts see the same information read-only.

Select several rows with their checkboxes, or every row of the page with the header checkbox, to set the status, team, assignee or root cause of all of them at once from the bar that appears above the table, over the row with the number of calls (it does not move the table) and stays at the top of the window while you scroll the table. The selection stays after each change, so several changes can be applied to the same calls; **Clear selection** empties it. **Apply suggestions** labels the selected calls without a root cause with their suggested one and leaves the labelled calls as they are.

**Export Excel** downloads every call that matches the filters, not only the current page, in three sheets: **NQ Calls** with the call fields and their follow-up (including the root domain and cause, and the suggested ones for calls without a root cause), **Comments** with every comment and its author, edits and deletion, and **History** with every follow-up change.

## Call details and activity

Click a row to open its details beside the table. The header shows the service, result, Operator, Campaign, time and place of the call, followed by its status, team, assignee and root cause (with its suggestion) and who changed them last.

**Activity** is a timeline of the call: comments with their author and time, and every change of status, team, assignee, root domain or root cause with the previous and new values. Write in the comment box and press **Add Comment** or Ctrl+Enter to share a comment with every user of the workspace. Comments keep line breaks and accept up to 5000 characters.

Admins and super-admins can delete the history: the **×** of a change deletes that entry, **Clear history** above the timeline deletes the whole history of the call, and **Clear history** in the bar of the selected calls deletes the history of all of them. Only the history is deleted: the status, team, assignee, root cause and comments stay, and the deletion is recorded in the audit log. A deleted history cannot be recovered (importing an older NQ Call Tracking package adds back the entries it contains), and the Progress View counts only the remaining changes.

Authors can edit and delete their own comments, and admins and super-admins can edit or delete any comment. Edited comments show **edited**; deleted comments leave a note with who deleted them and when, and the history keeps the previous text of every edited or deleted comment.

**Call Details** lists the main fields of the call, its location (opened in OpenStreetMap) and its CDR, followed by every non-empty field of the original CDR row, which you can filter by name or value.

When another user changes a call after you loaded it, your change is refused and the list reloads, so nobody overwrites a newer follow-up by mistake. The open page refreshes the calls and the open call every minute.

## Statuses and teams

**Statuses & Teams** (for `user-editor` accounts and above) configures the values shared by the workspace. Each status and team has a name, a colour and a position; statuses marked **Closed** count as closed in the summary and are left out by **Open calls only**. The first status is shown for calls nobody has followed up yet.

The defaults are the statuses Open, Under Investigation, Pending Information, Resolved (closed) and Not Applicable (closed), and the teams RAN Optimisation, Core Network, IMS / VoLTE, Transport and Device & Test Setup. Renaming a status or team updates every call that uses it. A status or team that is still used by a call cannot be removed; move its calls first.

In **Statuses & Teams**, the **Members** button of each team (*Everyone* or the number of members) opens a dialog to choose the workspace users that belong to it, with a filter and **Select All / None**; a user can belong to several teams. The members are saved with **Save**. When a call has a team with members, its **Assignee** list offers only them, and moving the call to a team its assignee does not belong to clears the assignee. A team without members accepts every user of the workspace.

## Root causes

**Root Causes** (for `user-editor` accounts and above, beside Statuses & Teams) configures the root cause taxonomy of the workspace: **domains**, each with a colour and its **causes**. The defaults are:

| Domain | Causes |
| --- | --- |
| RF | DL interference, UL interference, Coverage, BLER |
| RAN | Handover failure, RRC layer, Inter-RAT transition, Low throughput, Paging |
| Core 2G/4G/5G | EPS bearer deactivation, TAU reject, NAS mobility management, WhatsApp session in GSM |
| Core EPSFB | EPS fallback failure |
| IMS/E2E | No QCI1 established, VoLTE core, E2E trace required |
| AAA | Authentication/Authorization |
| Protocol | Packet loss, TCP connection errors, DNS, HTTP, Data transfer timeout, No DL packets, Latency |
| Device | Device or test setup |

Each domain and cause has **keywords**, separated by commas, that suggest a root cause. With the default **suggestion rule**:

1. A domain keyword found in the CDR **Failure Classification** chooses the domain (for example *RF Problems* → RF).
2. A cause keyword found in the **Failure Category**, **Failure Subcategory** or **Failure Comment** chooses the cause, among the causes of that domain, or of every domain when no domain matched (*DL interference problems* → RF · DL interference; *E2E Trace Required* with *Packet Loss* → Protocol · Packet loss).
3. When the CDR leaves the cause unresolved, the **comments** of the call are read the same way: a cause of the CDR domain (or of any domain), or else a domain keyword. These suggestions read *Suggested from comments*.

*E2E Trace Required* is not a domain: it says that an end-to-end trace is needed to find the cause, so its category (Packet Loss, Low Throughput, Coverage…) chooses the root cause.

The Root Causes dialog describes the rule of the workspace. **Suggestion Rule**, in that dialog and in the Root Cause Analysis panel, shows it to every user; **admins and super-admins** change there the call fields that choose the domain and those that choose the cause (Failure Classification, Category, Subcategory, Comment, Phase and Technology, Result, Test Name, Technology and Direction), whether the cause is looked for only among the causes of the domain found, whether the comments are read when the cause is unresolved and whether they can choose the domain, and whether keywords match whole words or any part of the text. **Default Rule** returns to the rule above. The rule applies at once to the suggestions, the Root Cause Analysis and Apply suggestions, never changes the root causes already set, and travels with the NQ Call Tracking (an import applies it when the destination workspace has not chosen its own).

When nothing names the cause — for example an interference that does not say DL or UL — only the domain is suggested. Domains and causes are tried from top to bottom, so their order (↑ ↓) sets the priority when several match. Keywords match whole words or phrases, ignoring case, underscores and repeated spaces: `rf` matches *RF Problems* but not *performance*. The defaults are a starting point drawn from the NetCheck CDR failure fields; review them in each workspace. **Add missing defaults** adds the default domains and causes that are not in the list and keeps the existing ones with their keywords.

Renaming a domain or cause updates every call that uses it; a domain or cause still used by a call cannot be removed. **Require a root cause to close a call** refuses moving a call to a closed status while it has no root domain.

## Reporting Jobs

Reporting Jobs include a **Non-Qualified Calls** artifact with the Executive Summary, the Progress Status and the Root Cause Analysis of the calls in PowerPoint, Word and/or Excel. Each job chooses its own filters (the same as the Filters panel), the period of the progress timeline, whether to include only open calls and whether the Root Cause Analysis counts the suggested root causes. See [Reporting](reporting.md).

## Storage and portability

The module stores its data in the workspace database, visible in [Admin → Database Management](administrator-config.md):

| Table | Content |
| --- | --- |
| NQ Calls | The indexed NQ rows of every CDR (rebuilt automatically). |
| NQ Call Sources | Which CDR revision each indexed CDR comes from. |
| NQ Call Tracking | The status, team, assignee, root domain and cause, and version of each followed-up call. |
| NQ Call Comments | Every comment with its author, time, edits and deletion. |
| NQ Call History | Every change of status, team, assignee or root cause and every comment edit or deletion. |
| NQ Call Options | The configured statuses and teams. |
| NQ Team Members | The users that belong to each team. |
| NQ Root Causes | The root cause domains and causes with their colours and keywords. |

The follow-up — statuses, teams with their members, root causes with the Require setting, tracking, comments and history — travels as **NQ Call Tracking** with Admin → Import / Export / Transfer, Full Workspace and Full Environment packages, workspace transfers, and backups and restores. Imports merge it into the destination workspace: missing statuses, teams, root domains and causes are added, a call's newer follow-up replaces an older one, and comments and history entries are added once, so importing the same package again changes nothing. The follow-up applies to the destination calls with the same identity, so import the same CDRs there to see it.
