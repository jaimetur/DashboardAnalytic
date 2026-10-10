# Non-Qualified Calls

Non-Qualified Calls brings the CDR Drive Test follow-up into DriveTest Analyzer as an **NQ Analysis Center**: an executive summary of every call and test that did not complete, a drill-down table of those calls, and a shared follow-up of each one that every user of the workspace sees. Each call is followed through six sections — **General**, **RCA**, **Failure Details**, **Analysis**, **Implementation** and **Planning** — with a Root Category and Root Cause decided from three sources (the RCA script, the NetCheck RCA of the CDR and the analysts), an NQ Call Status that follows the phases by rules or is set by hand, a responsible team, an assignee and a comment thread. Dashboards show the lifecycle of the calls, their phases, where they fail and how the root cause sources agree.

The module is in development, so its main tab can show a red **ALPHA** label (see Interface Settings). It is active for every user of a new deployment; admins and super-admins restrict it in [Admin → Features Activation](administrator-config.md).

## Which calls are Non-Qualified

A Non-Qualified (NQ) call is any Voice or Speech call, or any Data test, whose result is not **Completed**: for example **Failed** and **Dropped** Voice calls and **Failed** and **Cutoff** Data tests. The result is read from the processed `status` field of the CDR, or from `Call_Status`, `Test_Result` or `Test_Status` when it is missing. Rows without a result are not included.

Every ready Voice, Speech and Data CDR of the active workspace is indexed as a background task, shown in the floating background tasks card: the first time the page opens, and then, when a CDR is added, reprocessed or deleted, once nobody has used the application for two minutes (the pages refreshing themselves do not count), so the page never waits for the indexing. The top of the **Filters** panel shows how many NQ calls and CDRs are indexed, when they were last indexed, and the CDRs waiting to be indexed or the indexing in progress, after which the page reloads its calls; **Reindex** indexes the calls of every CDR again at once, in the background (their follow-up is kept), even when no CDR has changed. **Export PowerPoint** and **Export Word**, on the right of the indexing badge and Reindex, download the Executive Summary (its indicators and every breakdown on one slide), the Progress Status and the Root Cause Analysis of the filtered calls with the look of the page (indicator cards, breakdowns, donuts, timeline, age and workload, root domains and causes, Classic vs WhatsApp, and the detail tables), the report selection on the cover (with the period chosen in the Progress View), the same document as the [Reporting](reporting.md) artifact; a progress dialog stays open while it is prepared.

Each call keeps a stable identity: its NetCheck `JOIN_ID`, the identifier of each voice call and data test that is the same in the Daily and the Final CDRs. Without a `JOIN_ID`, the identity is its service, Operator, Campaign and test or session identifier (`Test_ID` or `Session_id` for Data tests, `Session_ID_A` for Voice and Speech calls; without one, its subscriber, test name and start and end times). Its status, team, assignee, root category and cause, fields and comments therefore stay with it when its CDR is reprocessed or uploaded again, and when the Final CDR of its campaign replaces the Daily ones. When the same call appears in several CDRs, it is listed once (see [Daily and Final CDRs](#daily-and-final-cdrs)).

Speech CDRs list one row per speech sample: Non-Qualified Calls lists each Speech **call** once (with the number of its Non-Qualified samples), and each sample keeps its own follow-up in the call details.

## Daily and Final CDRs

A call can be in a Daily CDR, in several cumulative Daily CDRs and in the Final CDR of its campaign (see [CDR Type](workspace-management.md#cdr-type-final-weekly-and-daily)). It is listed once, with the data of its most recent CDR: the Final CDR before the Daily ones, then the CDR with the newest calls. Its analysis is shared by every CDR that contains it, so choosing a Daily CDR, a cumulative Daily CDR or the Final CDR in the **CDRs** filter shows the same follow-up; with CDRs chosen, each call shows the data of the most recent of them.

A badge below the result tells how the other CDRs see the call (hover it for the CDR shown and the latest one):

- **Changed between CDRs**: its result or failure is different in another CDR.
- **Newer version in another CDR**: a more recent CDR that is not chosen in the CDRs filter has the call.
- **Not in the Final CDR**: the call is only in Weekly or Daily CDRs while a Final CDR covers its campaign.
- **Completed in a newer CDR**: the most recent CDR has the call Completed. These calls are listed only while that CDR is not chosen in the CDRs filter, or when **CDR Version** selects them.

The **CDR Version** filter selects the calls of each case (**Latest version** are the others). **Call Details** lists every CDR that contains the call, Final, Weekly or Daily, with the date of its newest calls and the call's result in it. The analysis of a call is lost from view only when no loaded CDR contains it any longer (for example, it is not in the Final CDR and its Daily CDRs are deleted); it stays in the database and comes back if a CDR with the call is loaded again.

## Filters

The **Filters** panel restricts the summary, the table and the Excel export together:

- **CDRs**, **Campaign**, **Operator**, **Operator_Vendor**, **Vendor_Operator**, **Vendor**, **Region**, **Cluster**, **City**, **Service**, **Technology**, **Test Name**, **Result**, **Failure Classification** and **Failure Category**, from the indexed calls. **Operator_Vendor** is the `<Operator>_<Vendor>` identity, **Vendor_Operator** the same identity as `<Vendor>_<Operator>` (both stay in sync) and **Vendor** the vendor alone; **City** offers the workspace **Main Cities** first.
- **Status**, **Status Set** (**Automatic** when the status follows the [Status Rules](#status-rules), **By hand** when an analyst chose it), **Team**, **Assignee**, **Root Domain**, **Root Category** and **Root Cause**, from the follow-up. **Unassigned** selects calls without a team or assignee, **Not classified** calls without a root domain or category and **No cause** calls without a root cause.
- **CDR Version** (see [Daily and Final CDRs](#daily-and-final-cdrs)).
- Every list and Yes / No [field](#fields-and-sections) entered by the analysts or derived from the call (for example Session Type, Analysis Status or Planned Status), under **Analysis Center Filters**; **Empty** selects the calls without a value.
- **Search** finds text in the call fields (Operator, Vendor, Campaign, Region, City, Technology, test, result, failure fields, cell, `JOIN_ID` and the CDR columns of the table), in the fields entered by the analysts and in the comments.
- **Open calls only**, **Assigned to me** and **Without comments**.

Selecting every value of a filter, or none, applies no restriction. Active filters appear as chips at the top of every panel (Summary, NQ Rate by Campaign and Operator, Progress View, Lifecycle & Phases, Root Cause Analysis, Root Cause Sources and the table), including those set from the Progress View and the Root Cause Analysis (NR Mode, Call Type, Period, Age of Open Calls, root domain and cause with suggestions, eNB/gNB); click a chip to remove it. The NQ Rate panel dims the chips of the filters it does not use. **Reset Filters** clears them all.

The selection is shared: it is saved in the workspace, so every user finds the last filters applied, in any session and on any device. **Assigned to me** always refers to the user viewing the page.

## Calls, Dashboards or every panel

A bar below the Filters, which stays at the top of the window while you scroll, chooses what the page shows under them: **Calls** (the [Non-Qualified Calls](#non-qualified-calls-panel) table, with the number of calls that match the filters), **Dashboards** (the Summary, NQ Rate, Progress View, Lifecycle & Phases, Root Cause Analysis and Root Cause Sources panels) or **All panels**. Each browser remembers the choice for each workspace. A click on a chart of the Dashboards filters the calls as usual, and the bar tells how many calls are left.

Only the panels on screen are calculated: a panel of the other view, or a folded one, is calculated when it is shown, so a change of the filters only waits for what you are looking at.

## Summary

The **Summary** panel is the executive view of the filtered calls: the number of Non-Qualified Calls, how many are open and closed, how many are attended (followed up with a change or commented), and how many have a responsible team or comments. Breakdowns by Service, Result, Status, Team, Root Domain, Root Category, Root Cause, Failure Classification, Campaign, Operator, Vendor, Region, Cluster and City show where the calls concentrate, six per row and with the same colours as in the one-slide Executive Summary of the PowerPoint and Word (each status, team and root domain in its colour, root categories and causes in the colour of their domain, the other values in a fixed palette). Campaigns read as everywhere in the tool (*UK_Q2_SA_2026* reads *2026-Q2-SA*; see [Campaign ordering](technical-considerations.md#campaign-ordering)) and still filter by the full campaign.

Click any bar to drill down: the table shows only that value. Click the same bar again to remove that filter. Fields marked **Summary breakdown** add their own breakdown, in the colours of their values (those entered by the analysts or derived also drill down).

## NQ Rate by Campaign and Operator

The **NQ Rate by Campaign and Operator** panel, below the Summary, is the management view of the campaigns: for each campaign and operator, how many of **every** call of the CDRs (qualified or not) are Non-Qualified, and their share. Each call counts once, in the most recent CDR that has it (the Final CDR before the Daily ones), so a call Completed in the Final CDR is no longer Non-Qualified.

- One tab per service (Voice, Speech and Data; **All services** adds them up when there are several).
- Cards with the overall rate and the rate of each operator, each operator named in its Operator Maps colour.
- A heat map: each cell shows the rate and *Non-Qualified / all calls*, coloured in pastel tones from soft mint (none) through apricot to dusty rose (the highest rate of the table); the Total column and row sum each campaign and operator.
- A click on a cell or card shows only those calls in the other panels; a second click removes the filter.

Only the **CDRs**, **Service**, **Campaign**, **Operator** and **NR Mode** filters apply: the other filters describe Non-Qualified Calls only, so changing them does not recalculate the panel, and its counts are reused until the CDRs are indexed again. The PowerPoint and Word exports and the Reporting artifact include the heat map of each service after the Executive Summary.

## Progress View

The **Progress View** below the Summary shows how the follow-up advances for the filtered calls:

- Indicators: calls, open and closed calls, calls attended (with a follow-up change or a comment), commented, with a team and assigned, and the average days to close.
- Donut charts **By Status**, **By Team**, **By Assignee**, **By Service** and **By Result**; each legend shows the full name with its count and share; hovering a slice shows its value, count and share, and a click on a slice or a legend entry filters the calls by that value.
- A timeline per **week**, **month**, **quarter** or **year** of the calls detected, attended, commented, closed and reopened (hover a period to read all its values), with a table that adds the status changes, the open backlog at the end of each period and the average days to close.
- The age of the open calls, the workload of each team and assignee (open, closed and total calls) and the recent activity.

As in the Summary, a click drills down into the calls: a slice or legend entry of a donut, a period of the timeline (in the chart or its table: the calls detected in that period), an age bar (the open calls of that age) or a team or assignee row shows only those calls; click it again to remove that filter. The User Activity table is informative only.

## Lifecycle & Phases

The **Lifecycle & Phases** panel of the Analysis Center follows the filtered calls through their follow-up:

- Indicators: the calls, how many have an **Automatic Status** (following the Status Rules) and a **Status by Hand**, how many are open and closed, and how many are **Stalled** (open without any change for 14 days or more). A click on Automatic, By Hand, Open or Closed shows only those calls.
- **NQ Call Status Pipeline**: a bar with the share of each status and one card per status, the open ones in their order and then the closed ones, with its calls, share and average age; a click on a card filters by that status. Each card shows the [Status Rules](#status-rules) that set it: **Rule N** (the order they are tried in) with the field and its values in their colours, for example *Rule 6 · Analysis Status · Ongoing* on Under Analysis, and *When no rule applies* on the first status. A click on a rule shows the calls that meet it.
- **RCA Identification**: how many calls have a root category or cause selected and how many not, each row drilling down into its calls.
- One card per list field of the **Analysis**, **Implementation** and **Planning** sections (for example Analysis Status, Implementation Status and Planned Status): a bar with the share of each value and a row per value (and **Empty**) that drills down into its calls.
- **Time in Each Status**: the average days the calls stayed in each status before moving, from the history of their status (set by hand or by the rules).
- **Most Frequent Moves** between statuses.
- **Stalled Open Calls**: the open calls without changes for the longest, with their status, Operator, Campaign, City and days without change; click one to open it.

**Status Rules** (for `user-editor` accounts and above) opens the rules from the panel.

## Root Cause Analysis

The **Root Cause Analysis** panel shows where the filtered calls fail:

- Indicators: the calls, how many have a root cause (**Labelled**), how many are counted with their **Suggested** root cause and how many are **Not classified**. **Count suggested root causes** (on by default) counts the calls without a root cause with the one suggested by their CDR failure classification; turn it off to count only the labelled calls.
- **By Root Domain** and **By Root Cause** bars, in the colour of each domain.
- **Classic vs WhatsApp** (Voice and Speech calls whose test name contains WhatsApp, the other calls, and the Data tests), **NSA vs SA** and **Technology** tables with the calls of each root domain.
- **eNB / gNB with most calls**: the node of the last cell of each call's `Cell_ID` chain (the cell where it ended): identities above 28 bits are NR cells (gNB = NCI / 4096), LTE cells give their eNB (ECI / 256) and smaller identities are 2G/3G cells. The site, host (OSS) and vendor come from the workspace **Vodafone** and **Three** cell mapping datasets when they list the node; otherwise the vendor is the call's.
- A click on a bar, on the first column or the Total of a table, on a cell of a domain, or on an eNB/gNB row shows only those calls (for example the NSA calls of RF), and a second click removes the filter. With **Count suggested root causes** on, the domains and causes include the suggested ones, as the counts do; with it off, only the labelled root causes.

## Root Cause Sources

The **Root Cause Sources** panel of the Analysis Center compares the three root cause sources of the filtered calls:

- Indicators: how many calls have **RCA Script** results, a **NetCheck RCA** classification and a **Selected** Root Category or Cause, and how often the sources agree: **Script ↔ Selected** and **NetCheck ↔ Selected** (the category, or the cause when the source maps to no category, the analysts selected is the one the source proposes, mapped onto the catalog by its keywords) and **Script ↔ NetCheck**.
- Three hierarchies side by side: the **RCA Script** Suggested Category → Cause, the **NetCheck RCA** Failure Category → Subcategory of the CDR and the Root Category → Root Cause **Selected by the Analysts**; a category or cause of the analysts drills down into its calls.
- **Selected Root Domains**, in the colour of each domain, drilling down by domain.
- **RCA → Selected Root Category**: for the RCA Script or NetCheck tab, how the categories the source maps to relate to the categories the analysts chose; the cells where both agree are outlined.

The panel shows how many RCA script results are imported and how many match calls; **RCA Script Results** (for `user-editor` accounts and above) imports them (see [RCA script results](#rca-script-results)).

## Non-Qualified Calls panel

**Join ID**, centred in the title bar of the panel, finds calls by their `JOIN_ID`: type or paste one or more, separated by commas, spaces or lines (whatever their case), to list the calls with exactly those IDs; it is kept with the shared selection and shown among the active filters.

The **Non-Qualified Calls** table lists one row per call with its start time (to the minute; hover it for the seconds) and service (and, for a Speech call, its number of Non-Qualified samples), Operator and Vendor, Region and Cluster, City and Campaign, test and technology, result with the failure classification and category (hover a failure to read its subcategory and comment) and the CDR version badge, then its team and assignee, the RCA fields chosen as columns (by default RCA Suggested Cause and Netcheck Suggested Cause), its Root Category and Root Cause, the other fields chosen as columns (by default Analysis Status), its status and comments. The header of every field is topped with the colour of its section (the Root Category and Root Cause with the RCA yellow). The default columns fit screens of 1440 px and wider without scrolling sideways: long values wrap on two lines or are shortened and shown whole when you hover them. Drag a column header onto another to move that column before or after it; each browser remembers the order for each workspace, columns added later take their default place, and **Default column order** puts every column back. Reloading the page returns to the position it was scrolled to.

**Analysis Center**, in the toolbar of the table (for `user-editor` accounts and above), opens the configuration of the workspace: [Fields & Sections](#fields-and-sections), [Statuses & Teams](#statuses-and-teams), [Status Rules](#status-rules), [Root Cause Catalog](#root-cause-catalog), [RCA Script Results](#rca-script-results) and **Additional Columns**.

**Additional Columns** chooses, for every user of the workspace, the optional columns shown after Result / Failure (Session Type (CDR) before Test / Technology): `JOIN_ID`, NR Mode, Cell ID, Direction, Session Type (CDR) (the CDR's `Session_Type`), End Time and CDR, the fields of the Analysis Center, grouped by section (the same choice as **Table column** in Fields & Sections), and the columns of the CDRs (for example `Cellname_A`, `Region_A` or `Auto_RCA_Category_A`), which show the value of the CDR version shown for each call. Each CDR column can go to the **Table** (up to 12), and then also to the Excel export, or to **Excel** only (up to 100 more). Choosing CDR columns indexes the calls again. Every optional column sorts the table and has its filter: Region, Cluster and CDR use their filters of the Filters panel, `JOIN_ID`, NR Mode, Cell ID, Direction, Session Type and End Time add theirs under **Additional Columns Filters**, and the CDR columns filter from their header only; every one offers **Empty** for the calls without a value. The Filters panel shows the **Default Filters**, then the **Analysis Center Filters** and the **Additional Columns Filters**. Related values share a column, one below the other, so the table fits in the panel. Every name of a column header (for example *Service*, *Result*, *Team* or *Assignee*) sorts the table when clicked, and the funnel beside it opens, right below the header, that field's values to filter by them: search them by name, tick them (**Select All / None** ticks or clears the values shown; the causes are grouped under their domain) and **Apply** (root categories and causes are grouped under their domain). A column filter is the same selection as the Filters panel and its chip: the funnel is filled while that field is filtered. Long values are shortened and shown whole when you hover them; on screens narrower than 1600 px the Comments column shows the number of comments and the latest one when you hover it. The table is paginated with 25, 50, 100 or 200 rows per page.

Users with the `user-editor`, `admin` or `super-admin` role change the **Status**, **Team**, **Assignee**, **Root Category** and **Root Cause** directly in the row, each from a list that shows every value as a pill in its colour (with a search box for long lists, and the arrow keys to move); each value keeps the colour of its status, team or root domain (a root category is filled with the colour of its domain, a root cause outlined with it). The Root Category and the Root Cause are chosen independently, each from a list grouped by domain (search it by name; the current value is ticked): the values the RCA sources of the call propose come first, and the root causes of the domain of the chosen category come before the other domains (and the categories of the domain of the chosen cause). While a call has no root category and cause, its recommended ones are shown below them, with a dot for the confidence of the recommendation (green high, amber medium, grey low), and a click accepts them (see [Root cause recommendation](#root-cause-recommendation)). Choosing a status sets it by hand: the list then offers **↺ Back to automatic** to give it back to the Status Rules. Below the status, each row tells whether it is **Auto** or set **By hand** and when its follow-up last changed and who changed it (hover it for the exact time). The status, team, assignee and root cause lists widen with the window. The **›** button beside the comments opens the call. The Comments column shows how many comments a call has and its latest comment; click it to read the thread or add a comment. `user-viewer` accounts see the same information read-only.

List and Yes / No fields entered by the analysts and shown in the table are chosen in the row too, from the same coloured lists; the other fields entered by the analysts are filled in the section of the call, and the fields from the CDR, the RCA script or derived from the call are shown read only.

Select several rows with their checkboxes, or every row of the page with the header checkbox, to set the status (or **↺ Back to automatic**), team, assignee, root category, root cause or a list or Yes / No field of the analysts (**Set field…**) of all of them at once from the bar that appears above the table, over the row with the number of calls (it does not move the table) and stays at the top of the window while you scroll the table. The selection stays after each change, so several changes can be applied to the same calls; **Clear selection** empties it. **Accept recommendations** gives the selected calls without a root category and cause their recommended ones and leaves the others as they are.

**Export Excel** downloads every call that matches the filters, not only the current page. Its **NQ Calls** sheet has two header rows coloured like the meeting workbook: the first names the section of each column (merged over its columns, in the colour of the section) and the second the field, in a lighter shade of it (lighter still for values from the CDR, the RCA script or derived). The status of each block stands out in a darker shade: NQ Call Status in General, Analysis Status, Implementation Status and Planned Status (the first list of each phase). The columns are:

1. **Call**: `JOIN_ID`, the Call Key and the CDR of the call first, to find a call at once, then Service, Start and End Time, Operator, `Operator_Vendor`, `Vendor_Operator`, Vendor, Campaign, NR Mode, Region, Cluster, City, Technology, Test Name, Session Type (CDR), Direction, Result, Failure Phase, Failure Technology, Cell ID, Latitude, Longitude, its CDR Version, the Latest CDR and the Non-Qualified samples of Speech calls.
2. Every field of the Analysis Center marked **Excel**, in the order of [Fields & Sections](#fields-and-sections), under its section (Failure Comment in Failure Details): NQ Call Status is followed by **Status Set** (Automatic or By hand); the RCA block ends with the **Root Domain**, the **Recommended Root Category** and **Root Cause**, the **Recommendation Sources** and the **Selected Root Category** and **Root Cause**; and **Comments** holds every comment of the call, one per line with its date, time and author.
3. The CDR columns chosen for the table or for Excel in **Additional Columns**, then **Updated By** and **Updated At** (when the follow-up of the call last changed).

The other sheets are **Speech Samples** with the follow-up of each Non-Qualified sample of the Speech calls (when there are any), **Comments** with every comment and its author, edits and deletion, and **History** with every follow-up and field change.

## Call details and activity

Click a row to open its details beside the table. The header shows the service, result, CDR version, Operator, Campaign, time and place of the call, followed by its **NQ Call Status** (with **Auto** or **By hand**), team, assignee, Root Category and Root Cause (with the domain they give the call, and the recommendation while it has none), its phases on one row — **RCA Identification** (the root category, or *Recommended* or *Not started*) and the first list field of the Analysis, Implementation and Planning sections, each in the colour of its section (a click opens its tab) — and who changed the call last.

Below, the tabs of the call on one line, each in the colour of its section: **Activity**, **RCA**, **Failure Details**, **Analysis**, **Implementation & Planning** (both sections in one tab, each in its own subpanel) and **Call Details** in grey. Each tab counts, as *filled/total*, the fields of the analysts that already have a value (hover it to read it); the RCA tab shows ✓ once a root category or cause is chosen and ★ while a recommendation waits. Lists and Yes / No fields are chosen from the same coloured lists as in the table, as tall as the text boxes, and long texts (Proposed Measure, Findings…) open tall enough to write in:

- **Activity** (the General section): the fields of the analysts placed in General (if any), then the activity of the call — a timeline of its comments with their author and time and every change of status, team, assignee, root category, root cause or field with the previous and new values; a status moved by the Status Rules reads *The status followed the Status Rules…* after the change that moved it. Write in the comment box and press **Add Comment** or Ctrl+Enter to share a comment with every user of the workspace. Comments keep line breaks and accept up to 5000 characters.
- **RCA**: the **Root Cause Decision** — the selected Root Category and Root Cause, the recommendation with its confidence and the sources that agree on it (**Accept** sets it), and a card per source with what it says (the script category → cause, the NetCheck category → subcategory) and the catalog values it maps to, with **Use** to take them; the other columns of the RCA script file of the call follow. Then the values of the RCA sources (script and NetCheck fields), read only.
- **Failure Details**, **Analysis** and **Implementation & Planning**: the fields of each section, with their description when you hover them; Failure Details also shows the **Last Cell ID** (the last cell of the Cell ID chain of the CDR, where the call ended) and the **Failure Comment** NetCheck writes in the CDR. Editors change the fields of the analysts; an empty field that proposes a CDR value (for example Failure Latitude and Longitude) offers **Use the CDR value**. **Save** in any tab saves the changed fields of every tab together (the sections tell how many changes are unsaved, and another user's newer change is detected as for the status); fields from the CDR, the RCA script or derived from the call are shown read only, with their source.

For a Speech call, **Call Details** starts with its **Speech Samples**: its Non-Qualified samples with their result, failure, status, root category and cause and comments; open one to follow it up on its own (status, team, assignee, root cause, fields and comments), and **‹ Back to the call** returns to the call.

Admins and super-admins can delete the history: the **×** of a change deletes that entry, **Clear history** above the timeline (shown when the call has a history) deletes the whole history of the call, and **Clear history** in the bar of the selected calls deletes the history of all of them. Only the history is deleted: the status, team, assignee, root cause and comments stay, and the deletion is recorded in the audit log. A deleted history cannot be recovered (importing an older NQ Call Tracking package adds back the entries it contains), and the Progress View counts only the remaining changes.

Authors can edit and delete their own comments, and admins and super-admins can edit or delete any comment. Edited comments show **edited**; deleted comments leave a note with who deleted them and when, and the history keeps the previous text of every edited or deleted comment.

**Call Details** lists the CDRs that contain the call (when there are several), the main fields of the call (with its `JOIN_ID`, root domain, category and cause), its location (opened in OpenStreetMap) and its CDR, followed by every non-empty field of the original CDR row, which you can filter by name or value.

When another user changes a call after you loaded it, your change is refused and the list reloads, so nobody overwrites a newer follow-up by mistake. The open page refreshes the calls and the open call every minute.

## Statuses and teams

**Statuses & Teams** (for `user-editor` accounts and above, in the **Analysis Center** menu of the table) configures the values shared by the workspace. Each status and team has a name, a colour and a position; statuses marked **Closed** count as closed in the summary and are left out by **Open calls only**. The first status is the one of the calls that no [Status Rule](#status-rules) matches, such as the calls nobody has followed up yet.

The defaults are the statuses Not Attended, Open, Under Analysis, Under Implementation, Under Planning and Closed (closed), and the teams E2E stream, RAN Planning Coverage, RAN Planning Capacity, RF OPT (Hot Spots) WP2a, Operations, Netcheck, Successful Call-Excluded and PCI Planning Team. Renaming a status or team updates every call that uses it, and a renamed status is renamed in the Status Rules. A team that is still used by a call, or a status still set by hand on a call, cannot be removed; move those calls first. The calls whose status the Status Rules gave follow the rules again when their status is removed. **Default Statuses** and **Default Teams** leave only the defaults, in their order and colours (a status or team with the same name is kept, with its calls and members, and recoloured), and **Save** applies the change; then **Default Rules** in [Status Rules](#status-rules) puts the default rules back.

In **Statuses & Teams**, the **Members** button of each team (*Everyone* or the number of members) opens a dialog to choose the workspace users that belong to it, with a filter and **Select All / None**; a user can belong to several teams. The members are saved with **Save**. When a call has a team with members, its **Assignee** list offers only them, and moving the call to a team its assignee does not belong to clears the assignee. A team without members accepts every user of the workspace. Choosing only the assignee brings the call to their team (the first one in the list when they are in several) unless the call already has a team they belong to or a team without members.

## Status Rules

The **NQ Call Status** of each call is semi-automatic: it follows the **Status Rules** of the workspace until an analyst chooses it by hand. **Status Rules** (for `user-editor` accounts and above, in the Analysis Center menu and the Lifecycle & Phases panel) lists the rules in order; each sets a status when every one of its conditions holds, and the first rule that matches gives the status of the call. A condition reads a list or Yes / No field entered by the analysts or derived from the call, the team, the assignee, the root category or cause, or **Attended** (the call has a follow-up change or a comment), and is **is one of** or **is not one of** some values, **is empty** or **is not empty**. The rules do not name fixed values: they choose among the values of each list, so renaming a list value or a status renames it in the rules, and a removed value or field is taken out of their conditions (a rule left without conditions is removed).

The default rules, for the default fields and statuses, are:

1. **Closed** when Analysis Status is Rejected or Invalidated.
2. **Closed** when Implementation Status is Implemented.
3. **Under Planning** when Planned Status is Planned.
4. **Under Implementation** when Implementation Status is Not yet evaluated, Under evaluation or Evaluated.
5. **Closed** when Analysis Status is Finished.
6. **Under Analysis** when Analysis Status is Ongoing.
7. **Open** when the call is attended.

Otherwise the call is **Not Attended**. **Default Rules** shows them again, with the conditions on the fields the workspace still has; a rule whose default status is no longer one of the statuses (for example after renaming it) is marked to choose the status it sets, and the rules are saved once every rule has a status. The automatic status changes as soon as a field, a comment, the team, the assignee or the root cause of the call changes, and saving the rules, the fields or the statuses applies them to every automatic call at once. Choosing a status by hand, in the table, the call or the bulk bar, keeps it until **↺ Back to automatic**. The history tells the automatic changes apart, and the Lifecycle & Phases panel, the **Status Set** filter and the Excel export show which calls are automatic.

## Root Cause Catalog

**Root Cause Catalog** (for `user-editor` accounts and above, in the Analysis Center menu) configures the catalog the Root Category and the Root Cause of each call are chosen from, in three tabs with a filter:

- **Root Categories**: the categories of the analysts (by default the 22 of the meeting workbook: E2E, Poor Coverage LTE / NR / 2G/3G, DL and UL Interference LTE / NR / 2G/3G, UE / Test Setup Issue, Unclear, Operational, Invalidated, Procedure Overlap, Radio Configuration Inconsistency, High PRB Utilization, Mobility LTE / NR, No Failure/ Drop, IMSI Issue and VONR not Enabled in Source/Neighbor Site).
- **Root Causes**: the causes, those of the meeting workbook (NLOS due to clutter or terrain profile, LOS but weak signal, Potential E2E Issue…) together with the technical causes of the first catalog (DL interference, Handover failure, No QCI1 established, DNS…), 47 by default.
- **Domains**: the technical domains with their colour: RF, RAN, Core 2G/4G/5G, Core EPSFB, IMS/E2E, AAA, Protocol, Device and Operational.

The Root Category and the Root Cause of a call are chosen independently, as the analysts asked, while each category and cause belongs to a domain: the domain gives them their colour, groups their lists (with the causes of the domain of the chosen category first) and gives the call its **Root Domain** (the domain of its category, else of its cause), so the statistics by domain and the hierarchies of the RCA sources stay. Each value has **keywords**, separated by commas, that map the RCA script and NetCheck values and the comments onto the catalog; `a+b` needs both words (`coverage+lte` matches *DL coverage problems* of an LTE call, not of an NR one).

The suggestion rule of the workspace is described at the top. **Suggestion Rule**, there and in the Root Cause Analysis panel, shows it to every user; **admins and super-admins** change the call fields that choose the domain and those that choose the category and cause (Failure Classification, Category, Subcategory, Comment, Phase and Technology, Result, Test Name, Technology and Direction), whether the category and cause are looked for only in the domain found, whether the comments are read when the CDR leaves them unresolved and whether they can choose the domain, and whether keywords match whole words or any part of the text. **Default Rule** returns to the default: a domain keyword in the Failure Classification chooses the domain (*RF Problems* → RF), category keywords in those fields, the Failure Category, Subcategory and Comment and the technology of the call choose the root category, and cause keywords in the Failure Category, Subcategory and Comment the root cause (*DL interference problems* of an NR call → DL Interference NR · DL interference), then the comments. *E2E Trace Required* is not a domain: its category (Packet Loss, Low Throughput, Coverage…) chooses the cause. The rule applies at once to the suggestions, the Root Cause Analysis and the recommendations, and never changes the root causes already set.

Values are tried from top to bottom, so their order (↑ ↓) sets the priority when several match. **Add missing defaults** adds the default domains, categories and causes that are not in the catalog and keeps the existing ones with their keywords. Renaming a value updates every call that uses it; a value still used by a call cannot be removed. **Require a root category to close a call** refuses closing a call while it has no root category, whether its status is chosen by hand or a change of its fields makes the rules close it.

## Root cause recommendation

Every call gets a recommended Root Category and Root Cause, merged from its sources:

- **RCA script**: the Suggested Category and Cause of the [RCA script results](#rca-script-results) of its `JOIN_ID` (else its Auto_RCA_Category_A and Subcategory_A), mapped onto the catalog by name or keywords.
- **NetCheck RCA**: the Failure Classification, Category and Subcategory of the CDR, mapped by the suggestion rule.
- **Comments**: the comments of the call, when the CDR leaves the root cause unresolved.
- **Previous decisions**: the Root Category and Cause the analysts chose for at least two other calls with the same script or NetCheck values.

The category with most weight wins (the script and the previous decisions weigh 3, NetCheck 2 and the comments 1), then the best cause among the sources that agree on it. The confidence is **high** when two or more sources agree, **medium** when only the script or the previous decisions propose it and **low** otherwise. The recommendation is shown in the table, the RCA tab of the call and the Excel export, and **Accept** (one call) or **Accept recommendations** (the selected calls) sets it; the analysts can also use what one source proposes or choose any other value, and their choices teach the next recommendations.

## Fields and sections

**Fields & Sections** (for `user-editor` accounts and above, in the Analysis Center menu) configures the catalog of fields every call is followed up with, shared by every user, in the order of the Excel export. **Sections** renames and recolours the six sections (their tabs, the colours of the table headers and of the Excel; by default General blue, RCA yellow, Failure Details red, Analysis purple, Implementation green and Planning a darker green); chips above the fields show the fields of one section, and a filter finds them by name.

Each field has a name, a **section**, a **source** and a **type**:

- **Entered by the analysts**: a **List** of values, each with a colour, **Text** (up to 300 characters), **Long text**, **Number**, **Date** (YYYY-MM-DD) or **Yes / No**. **Propose the CDR value of** offers an empty field the value of a call field (*Use the CDR value* in the call; for example Failure Latitude and Longitude, Serving Cell, Band and Vendor when Failure, Host Network when Failure).
- **Follow-up of the call**: the NQ Call Status, Team Responsible, Asignee, Date last modification, Comments, Selected Root Category and Selected Root Cause. They can be renamed, moved to another section and reordered, but not removed.
- **From the CDR**: a call field, the last cell of the Cell ID chain (`last_cell_id`) or a CDR column (`column:<name>`, indexed automatically), read only (for example the Netcheck Failure Classification, Suggested Category and Suggested Cause, the Last Cell ID and the Failure Comment).
- **From the RCA script**: a column of the [RCA script results](#rca-script-results), read only (Auto_RCA_Category_A … RCA Suggested Cause).
- **Derived from the call**: a list whose values have keywords looked for in some call fields; the first value whose keywords appear is the value of the call (Session Type: WhatsApp, MULTI-RAB, CALL, HTTP Transfer, Browsing & Streaming and Interactivity & Ping from the CDR `Session_Type` and Test Name).

Each field can be a **Table column**, go to **Excel** (every field by default), be a **Summary breakdown** (lists and Yes / No) and, when the analysts enter it, be **Required to close**: a call cannot be closed, by hand or by a change of its fields, while a required field is empty. A description is shown when hovering the field. The order of the list (↑ ↓) is the order of the fields in their section and in the Excel export. Renaming a list value updates every call that uses it and the Status Rules; a value or a field still used by a call cannot be removed, and the type and source of a field with values cannot change.

The default catalog is the 37 fields of the meeting workbook, in its order, with the Last Cell ID and Failure Comment of the CDR in Failure Details: **RCA** (Auto_RCA_Category_A, Auto_RCA_Subcategory_A, Auto_RCA_Category_B, Auto_RCA_Subcategory_B, RCA Suggested Category, RCA Suggested Cause, Netcheck Failure Classification, Netcheck Suggested Category, Netcheck Suggested Cause, Selected Root Category, Selected Root Cause), **General** (NQ Call Status, Team Responsible, Asignee, Date last modification, Comments), **Failure Details** (Session Type, Failed Party (MOC/MTC) (UE1/UE2), Host Network when Failure, Last Cell ID, Serving Cell when Failure (proposing the Last Cell ID), Band when Failure, Vendor when Failure, Failure Comment), **Analysis** (Analysis Status, Tunnel Failure, Needed Technology, Failure Latitude, Failure Longitude, Problem Location, Solution Location, Proposed Measure, Findings), **Implementation** (Implementation Status, Implementation Proposal, Implementation Site, Notice to VF3) and **Planning** (Planned Status, Planned Date).

### Catalog workbook

**Export Catalog** downloads the whole catalog as an Excel workbook that is easy to edit and to import again: **About** (how to edit it), **Sections** (key, name and colour), **Fields** (order, section, name, key, type, source, source reference, table, Excel, summary, required, CDR value proposed and description), **Lists** (one row per list value with its colour and keywords), **Root Catalog** (each domain, root category and root cause with its domain, colour and keywords), **Statuses and Teams** (with the closed statuses and the team members) and **Status Rules** (one row per condition). **Import Catalog** reads that workbook, or the field list of the meeting workbook (the sections in the first row, the field names in the second, the kind of values in the fourth and the values of each list from the sixth), and previews what it adds before **Import**: new fields, list values, domains, root categories, causes, statuses and teams are added, the sections and Status Rules of the workbook are taken, and nothing is removed.

## RCA script results

**RCA Script Results** (for `user-editor` accounts and above, in the Analysis Center menu and the Root Cause Sources panel) imports the results of the RCA script: a CSV (comma, semicolon or tab separated) or Excel file with one row per call and the columns

| Column | Content |
| --- | --- |
| `JOIN_ID` | The NetCheck identity of the call (required; any case). |
| `Auto_RCA_Category_A`, `Auto_RCA_Subcategory_A` | Root cause category and subcategory found for the A side. |
| `Auto_RCA_Category_B`, `Auto_RCA_Subcategory_B` | The same for the B side. |
| `RCA_Suggested_Category`, `RCA_Suggested_Cause` | The root category and cause the script suggests. |

Column names are matched ignoring case, spaces and underscores, at least one RCA column is needed, and any other column (for example a confidence) is kept and shown with the call. **Download Template** gives an empty file with these columns and an example row. Choosing a file previews it — how many results match a call of the workspace, the columns found, the rows left out without a `JOIN_ID` and the repeated `JOIN_IDs` (the last row wins) — before **Import**. A new file adds its results and replaces those of the same `JOIN_ID`; **Replace the previous results** forgets every result imported before. The dialog lists the imported files with their results, date and user, and **Delete every result** removes them. Results whose `JOIN_ID` is not indexed yet apply as soon as the call is.

## Reporting Jobs

Reporting Jobs include a **Non-Qualified Calls** artifact with the Executive Summary, the NQ Rate by Campaign and Operator, the Progress Status, the Lifecycle & Phases, the Root Cause Analysis and the Root Cause Sources of the calls in PowerPoint, Word and/or Excel (the Excel export of the page). Each job chooses its own filters (the same as the Filters panel, including **CDR Version**), the period of the progress timeline, whether to include only open calls and whether the Root Cause Analysis counts the suggested root causes. See [Reporting](reporting.md).

## Storage and portability

The module stores its data in the workspace database, visible in [Admin → Database Management](administrator-config.md):

| Table | Content |
| --- | --- |
| NQ Calls | The indexed NQ rows of every CDR (rebuilt automatically), with their `JOIN_ID` and, for Speech samples, their sample identity. |
| NQ Call Sources | Which CDR revision each indexed CDR comes from, whether it is a Final, Weekly or Daily CDR and the date of its newest call. |
| NQ Call Population | Every call of every CDR, qualified or not, for the NQ rates (rebuilt automatically). |
| NQ Call Versions | Which CDR holds the latest version of each Non-Qualified call and how the CDRs differ (rebuilt automatically). |
| NQ Call Latest | The latest version of each Non-Qualified call with its mapped Operator and Vendor and its last cell, read by every panel (rebuilt automatically after the indexing or a change of the Operator and Vendor Maps). |
| NQ Call Tracking | The status (and whether it is automatic or set by hand), team, assignee, root domain, category and cause, and version of each followed-up call and Speech sample. |
| NQ Analysis Fields | The field catalog: each field with its section, source, type, values, colours, keywords and options. |
| NQ Analysis Field Values | The value of each field entered by the analysts for each call and Speech sample. |
| NQ Call Comments | Every comment with its author, time, edits and deletion. |
| NQ Call History | Every change of status (by hand or by the rules), team, assignee, root category or cause and field, and every comment edit or deletion. |
| NQ Call Options | The configured statuses and teams. |
| NQ Team Members | The users that belong to each team. |
| NQ Root Catalog | The domains, root categories and root causes with their domains, colours and keywords. |
| NQ RCA Results | The imported RCA script results, by `JOIN_ID`, with their file, date and user. |

The section names and colours and the Status Rules are kept in the workspace settings. The follow-up — sections, the field catalog with its values, statuses, teams with their members, the root cause catalog with the Require setting and the suggestion rule, the Status Rules, the RCA script results, the optional table columns, tracking, comments and history — travels as **NQ Call Tracking** with Admin → Import / Export / Transfer, Full Workspace and Full Environment packages, workspace transfers, and backups and restores. Imports merge it into the destination workspace: missing statuses, teams, domains, root categories and causes and fields (and list values) are added, the sections and Status Rules of the package are taken, a call's newer follow-up or field value replaces an older one, and comments, history entries and RCA results are added once, so importing the same package again changes nothing. Packages of the first version, with domains and causes only, are imported into the new catalog. The follow-up applies to the destination calls with the same identity, so the destination may load the CDRs later: their calls show their follow-up as soon as they are indexed. Both workspaces must run the same version: packages exported before calls were identified by their `JOIN_ID` use the former identities.

To copy only the configuration to another workspace or server, export or transfer **NQ Calls Configuration** (also a Backup component): the sections, the field catalog with its lists, the statuses, the teams with their members, the Status Rules, the root cause catalog with the Require setting and the suggestion rule, and the optional table columns, without RCA script results, follow-up, comments or history. Its import merges it like the configuration part of NQ Call Tracking: missing statuses, teams, fields, list values, domains, root categories and causes are added, the sections and Status Rules of the package are taken, and the table columns, suggestion rule and Require setting are taken only where the destination has none. Statuses and teams of the destination that the package does not have stay: remove them in **Statuses & Teams** if no call uses them.

When a workspace is first opened with this version, the follow-up of its indexed calls moves once to their `JOIN_ID` identities, and the follow-up of each Speech sample stays with that sample of its call.

The first time a workspace opens with the Analysis Center, its follow-up is kept and completed: its analysis fields join the default catalog (a field with the name of a default field keeps its values and takes its section and place), its root domains and causes become the catalog with the default categories, the first default statuses and teams are replaced while nobody had changed them (Under Investigation becomes Under Analysis, Pending Information Open, and Resolved and Not Applicable Closed), the statuses chosen before are kept by hand (only Open and the calls not yet followed up follow the Status Rules), and the default Status Rules are added. Workspaces that kept the first layout of the Analysis Center take, once, Failure Details (formerly Failure Event) in red and Implementation and Planning in green, the Last Cell ID and Failure Comment fields, Serving Cell when Failure proposing the last cell, and the Analysis fields in the order of the call panel.

## On phones

On a phone the page fits the width of the screen. The bar of [Calls, Dashboards or every panel](#calls-dashboards-or-every-panel) stays on one row, the filters and the indicators go two per row, the tabs of the NQ Rate, the Root Cause Sources and the call scroll sideways, and the tables of the Dashboards keep their first column in view while they scroll. Each call of the table is a card with the name of every value above it, its start time and service at the top and its select box in the corner; the header of the table stays above the cards as a row of chips that sort and filter, and the pager shows the page among the pages instead of the page numbers. The call details fill the screen and scroll as a whole with their tabs at the top (the chosen tab comes into view) and the phases two per row, and the dialogs of the Analysis Center fill the screen with their rows wrapped.

## Speed with large workspaces

The page stays quick with tens of thousands of calls: the latest version of every call (with its mapped Operator and Vendor) is kept in the **NQ Call Latest** table and rebuilt in the background after each indexing, so a filter change reads it with the current follow-up instead of working out every call again; the calls of a choice of CDRs are read once per request; the root cause suggestions are matched once for each combination of CDR values; the filters that count the suggested root causes are found once for all the panels of a filter change; and only the panels on screen are calculated. The pages never wait for the indexing or for a CDR being processed to read the calls.
