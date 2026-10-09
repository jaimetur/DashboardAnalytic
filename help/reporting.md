# Reporting

Use **Reporting** to collect artifacts from several modules in one **Reporting Job**, run it on demand or on a schedule, and email the artifacts with a clear description of each one and its filters.

> [!NOTE]
> **Feature activation.** **Reporting** is available to every user by default. Admins and super-admins allow or forbid it for roles, user groups or users in **Admin → Features Activation**. Creating, editing and running jobs requires `user-editor`, `admin` or `super-admin`.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Artifacts a job can include | [Open section](#artifacts) |
| Create, edit and run a job | [Open section](#reporting-jobs) |
| Email delivery | [Open section](#email-delivery) |
| Schedules | [Open section](#schedules) |
| Run history and downloads | [Open section](#run-history) |
| Portability | [Open section](#portability) |

## Artifacts

A job includes any combination of these artifacts. A user can only include artifacts of the modules activated for their account, and each run checks it again with the permissions of the job's author.

| Artifact | Content | Options |
| --- | --- | --- |
| **CDR Analysis** | The CDR Analysis export of every selected dataset: global KPIs, metric cards, CDF and comparison charts, grouped percentiles and the processed metrics table | PowerPoint and/or Word; CDRs chosen by hand or with an automatic choice (see below), applied in each NR Mode; in a **Metrics** row, the metrics of each CDR type (CDR Data, Voice and Speech; all by default); in a **Filters** row, the Operator, Operator_Vendor, Vendor, Region, Cluster, City (with Main Cities) and Campaign filters of Network Insights; and two single-choice rows, **Global Comparison** for the charts' grouping and **Global CDF Comparison** for the CDF curves (Operator by default) |
| **Network Insights** | RF quality overview with campaign deltas, RSRP and SINR CDFs, coverage and interference maps with their weakest areas (LTE and NR separately for LTE+NR), observed and licensed spectrum and network deployment | One report per entry, in PowerPoint and/or Word: NR Mode, technology, LTE/NR thresholds, grouping (Operator, Vendor, Region, Cluster, City, CDR type, Campaign; Operator stays checked unless Vendor is checked, as in the module), Operator/Operator_Vendor/Vendor/Region/Cluster/City/Campaign filters in one row and CDRs |
| **Dashboard** | One new Dashboard PowerPoint per entry, generated at each run | NR Mode first, which lists its Dashboards and CDRs (by hand, the Dashboard's own CDRs by default, or with an automatic choice, see below), then the Dashboard's own options, prefilled with its saved definition: Scope and Vendor comparison, CDR Data/Voice/Speech, date range and every Adaptative Filter (Operator, Operator_Vendor, Vendor, Market, Region, Cluster, City, Campaign, RAT, Session Type, Call Status and the Dashboard's Auto-calculated Fields). Filter values are the ones the selected CDRs offer; empty filters include every value |
| **Scoring** | One Scoring & GAP Analysis report per entry, in PowerPoint and/or Word (the Word document has one landscape page per slide), with the Best Network scoring and, when the methodology has Most Reliable points, the Most Reliable Network scoring in the same document. **Configure report…** chooses its scenarios (each with its filters, Main Cities included, and aggregation levels) and the content of each scoring with the same editor as Scoring & GAP Analysis, where saved report configurations can be loaded. The report content is required: until it is configured the entry shows *Not configured* and the job cannot be saved | NR Mode, CDRs (by hand or with an automatic choice, see below), methodology, GAP reference and the report content. An identical completed calculation is reused |

Add Network Insights, the same Dashboard or Scoring several times to include several configurations, for example a Network Insights report for NSA and another for SA, one for LTE and one for NR, or three Dashboards with two filter configurations each. Jobs saved with a single Network Insights selection show it as one entry. Modules that provide their own reports appear as additional artifacts: **Non-Qualified Calls** adds its Executive Summary, Progress Status and Root Cause Analysis in PowerPoint, Word and/or Excel (PowerPoint and Word show the indicator cards, breakdowns, donuts, timeline, workload, root causes and detail tables with the look of the page; PowerPoint or Word is always generated, and Excel is an optional extra with only the calls detail, their comments and history), with the filters of its Filters panel (Root Domain and Root Cause included), the period of the progress timeline, an open-calls-only option and whether the Root Cause Analysis counts the suggested root causes.

Filter and metric dropdowns open one at a time and close when clicking elsewhere. Each selector shows its name above it and reads **All** when every value or none is selected (no restriction, the default) or **N of M**; **Select All / None** selects or clears the listed values. The values listed are those of the CDRs the entry uses: the selected CDRs or, with every ready CDR, those of its NR Mode, and they update when the NR Mode or the CDRs change; every City selector offers **Main Cities** first. CDR Analysis, Network Insights, Dashboards and Scoring choose their CDRs by hand or with one of two automatic choices, made again at each run so CDRs added later are included: **Newest complete set of Data, Voice and Speech CDRs** (the newest CDR and its companions of the same campaigns) or **All complete sets of Data, Voice and Speech CDRs** (every CDR whose campaigns have Data, Voice and Speech CDRs). They apply to the entry's NR Mode, and CDR Analysis applies them in each NR Mode. While one is checked, the locked CDR list shows checked the CDRs it selects now, and unchecking it starts a manual selection from those CDRs. Jobs saved with every ready CDR use **All complete sets**.

Every artifact file is named `yyyymmdd_hhmmss - <Module> - <report name>` with the run timestamp, for example `20261006_093000 - Network Insights - NSA LTE.pptx`; artifacts with the same name get ` (2)`, ` (3)`… The ZIP of a run is named `yyyymmdd_hhmmss - Reporting - <job name>.zip`.

The same summaries are available directly: **Export PowerPoint** and **Export Word** in [CDR Analysis](datasets-analysis.md) ask which datasets to include (or export the open CDR as on screen), and **Export PowerPoint** and **Export Word** in [Network Insights](network-insights.md) export the current selection.

## Reporting Jobs

The **Reporting Jobs** table lists every job with its name, artifacts (each module in bold, with its entries indented below it when it has several), next run, recurrence, whether it sends email, the time of its last run and its status, followed by its actions in one row.

| Action | Result |
| --- | --- |
| ▶ Run now | Starts a run immediately, whatever the schedule |
| ⬇ Download | Downloads the artifacts of the last run as a ZIP |
| ✎ Edit | Opens the job in the editor |
| ⧉ Duplicate | Creates a disabled copy named "(copy)" |
| ⏸ / ⏵ | Disables or enables the schedule |
| × Delete | Deletes the job, its run history and artifacts |

Select **New Reporting Job** (or ✎ Edit on a job) to unfold the **Job Editor** inside the jobs table: right below the job being edited (highlighted), above the other jobs, or at the top for a new job. **Cancel**, the red **Close** button in its corner or **Save Reporting Job** folds it away again; with unsaved changes, Cancel, Close and opening another job ask before discarding them. The open editor is kept in the browser while you work, so reloading the page reopens it on the same job with its unsaved values, unless the job has changed on the server since then (imported, transferred, saved from another browser or updated by a rename in the Operator or Vendor Maps): then its saved version opens and the unsaved values are discarded. Enter a name, set the **Job enabled** switch beside it (a disabled job keeps its configuration but never runs on its schedule; ▶ Run now works either way), choose the schedule and the delivery, choose each artifact in its tab (the tabs sit on the artifact's panel; the selected one joins it) — CDR Analysis, Network Insights, PPT Dashboards, Scoring & GAP Analysis and Non-Qualified Calls, each in the colour of its module and with a check after its name when it is included — check it to include it and configure its entries, then **Save Reporting Job**. Each tab shows the icon of its module after the check, and the browser keeps the selected tab when the page is reloaded. An unchecked type keeps its configuration in the editor but is not generated. Each type offers its output formats as chips (at least one stays selected). Each artifact type and each entry has **Collapse/Expand**, remembered by the browser after reloading the page, and an entry's header names its NR Mode, technology or Dashboard. The fields of each entry share one row on wide screens, and CDRs appear in one card per type (CDR Data, Voice and Speech) with **Select All/None**, as in Network Insights.

## Email delivery

Enable **Send the artifacts by email** and enter the recipients separated by commas, semicolons or lines. Without email, a run only keeps its artifacts for download.

The email subject is the job name with the run time. Its body lists every attached file with its content and filters (datasets, Dashboard Scope and filters, Scoring CDRs, aggregation and filters, Network Insights selection) and every artifact that could not be generated with its reason.

Configure the SMTP server in **Config → Application Config → Email Delivery**; see [Application Config](app-config.md#email-delivery). A run whose attachments exceed the configured size limit fails with a clear message.

## Schedules

| Recurrence | Runs |
| --- | --- |
| Manual only | Only with ▶ Run now |
| Once | On the chosen date and time |
| Daily | Every day at the chosen time |
| Weekly | On the chosen weekdays at the chosen time |
| Monthly | On the chosen day of the month (the last day in shorter months) |

Times use the application timezone set in Application Config. The scheduler checks every 30 seconds.

> [!IMPORTANT]
> **Jobs run whenever the application is running.** The scheduler checks the jobs of every workspace, also when their workspace is closed or another workspace is open; jobs of the open workspace run in the server and the others in a separate worker that does not change the workspace open for users. Runs appear in the background tasks window with their progress. A run that fell due while the application was stopped starts at the next check; several missed runs become a single run.

## Run history

**Run History** shows each run with its trigger, start time, status (with how long the run took once it finishes), email result and artifacts, grouped by module as in the jobs table: one line per entry with its formats, such as `NSA LTE (PPT/Word)`, where each format links to its file. A run lists only the files it generated that still exist; a file that could not be kept appears with its error instead of a link. ⬇ downloads them all as a ZIP.

| Status | Meaning |
| --- | --- |
| Queued, Running | The run is waiting or generating; progress and the current step are shown |
| Sent | Every artifact was generated and emailed |
| Completed | Every artifact was generated; the job does not send email |
| Partial | Some artifacts failed; the others were emailed |
| Failed | No artifact was generated, or the email could not be sent |

Runs interrupted by an application restart are marked as failed. Artifacts are stored in `output/reports/reporting-jobs/` of the workspace, one folder per run.

## Portability

Reporting Jobs travel with **Admin → Import / Export / Transfer** (the **Reporting Jobs** element and Full Workspace), workspace transfers and backups. Imports add new jobs and replace jobs with the same name; dataset references are matched by file name in the destination workspace. Run history and artifacts are generated output and are not exported.
