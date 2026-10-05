# Reporting

Use **Reporting** to collect artifacts from several modules in one **Reporting Job**, run it on demand or on a schedule, and email the artifacts with a clear description of each one and its filters.

> [!NOTE]
> **Feature activation.** Reporting starts available to super-admins only. Super-admins allow or forbid it for other roles, user groups or users in **Admin → Features Activation**. Creating, editing and running jobs requires `user-editor`, `admin` or `super-admin`.

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
| **Dataset Analysis** | The Datasets Analysis export of every selected dataset, with every KPI and no filters: global KPIs, metric cards, CDF and comparison charts, grouped percentiles and the processed metrics table | PowerPoint and/or Word; every ready CDR (also future ones) or a fixed selection |
| **Network Insights** | RF quality overview with campaign deltas, RSRP and SINR CDFs, coverage and interference maps with their weakest areas (LTE and NR separately for LTE+NR), observed and licensed spectrum and network deployment | One report per entry, in PowerPoint and/or Word: NR Mode, technology, LTE/NR thresholds, grouping, Operator/Vendor/Campaign/Region/City filters and CDRs |
| **Dashboard** | One new Dashboard PowerPoint per entry, generated at each run | NR Mode first, which lists its Dashboards and CDRs (or **Every ready Data, Voice and Speech CDR of this NR Mode at each run**), then the Dashboard's own options, prefilled with its saved definition: Scope and Vendor comparison, CDR Data/Voice/Speech, date range and every Adaptative Filter (Market, Region, City, Campaign, Operator, Vendor, RAT, Session Type, Call Status and the Dashboard's Auto-calculated Fields). Filter values are the ones the selected CDRs offer; empty filters include every value |
| **Scoring** | One Scoring & GAP Analysis PowerPoint per entry | The Scoring calculation options: NR Mode, CDRs (or the newest complete set at each run), Operator/Vendor/Region/City/Campaign filters or Main Cities, aggregation levels, methodology and GAP reference. An identical completed calculation is reused |

Add Network Insights, the same Dashboard or Scoring several times to include several configurations, for example a Network Insights report for NSA and another for SA, one for LTE and one for NR, or three Dashboards with two filter configurations each. Jobs saved with a single Network Insights selection show it as one entry. Modules that provide their own reports, such as Non-Qualified Calls when it is ready, appear as additional artifacts.

The same summaries are available directly: **Summary PowerPoint** and **Summary Word** in [Datasets Analysis](datasets-analysis.md) ask which datasets to include, and **Export PowerPoint** and **Export Word** in [Network Insights](network-insights.md) export the current selection.

## Reporting Jobs

The **Reporting Jobs** table lists every job with its name, artifacts, next run, recurrence, whether it sends email and its last run.

| Action | Result |
| --- | --- |
| ▶ Run now | Starts a run immediately, whatever the schedule |
| ⬇ Download | Downloads the artifacts of the last run as a ZIP |
| ✎ Edit | Opens the job in the editor |
| ⧉ Duplicate | Creates a disabled copy named "(copy)" |
| ⏸ / ⏵ | Disables or enables the schedule |
| × Delete | Deletes the job, its run history and artifacts |

Select **New Reporting Job**, enter a name, check each type of artifact to include — Datasets Analysis, Network Insights, E2E Dashboards, Scoring & GAP Analysis and, when it provides artifacts, Non-Qualified Calls — and configure its entries, then choose the delivery and the schedule and **Save Reporting Job**. An unchecked type keeps its configuration in the editor but is not generated. Each artifact type and each entry has **Collapse/Expand**, remembered by the browser after reloading the page, and an entry's header names its NR Mode, technology or Dashboard. The fields of each entry share one row on wide screens, and CDRs appear in one card per type (CDR Data, Voice and Speech) with **Select All/None**, as in Network Insights.

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

**Run History** shows each run with its trigger, start time, status, email result and artifacts. Each artifact links to its file; ⬇ downloads them all as a ZIP.

| Status | Meaning |
| --- | --- |
| Queued, Running | The run is waiting or generating; progress and the current step are shown |
| Sent | Every artifact was generated and emailed |
| Completed | Every artifact was generated; the job does not send email |
| Partial | Some artifacts failed; the others were emailed |
| Failed | No artifact was generated, or the email could not be sent |

Runs interrupted by an application restart are marked as failed. Artifacts are stored under the application output folder in `reporting/`.

## Portability

Reporting Jobs travel with **Admin → Import / Export / Transfer** (the **Reporting Jobs** element and Full Workspace), workspace transfers and backups. Imports add new jobs and replace jobs with the same name; dataset references are matched by file name in the destination workspace. Run history and artifacts are generated output and are not exported.
