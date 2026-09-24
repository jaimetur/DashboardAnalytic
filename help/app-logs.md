# App Logs

App Logs records meaningful application and workspace events for operational review. It distinguishes the person associated with a workflow (**User**) from the account or process that performed each step (**Executed by**); automatic steps use `system`.

## Access and workspace scope

App Logs is available to authenticated users with the existing application roles. App Events show the active workspace's audit entries. Open a workspace in Workspace Management to review its events. When no workspace is active, the App Events table is unavailable; the live Execution Log still shows output from the running server process.

## App Events

Use the filters to narrow entries by **Date**, **User**, **Executed by**, **Type** and **Action**. User matching is case-insensitive and usernames display in lowercase. Select **Clear Filters** to restore the full list, or **Refresh** to request the latest entries. The table refreshes automatically every five seconds.

Events include authentication, ingestion and processing, report and Dashboard generation, configuration changes, imports, exports, backups and transfers. Background events retain the requester and `system` executor separately.

## Execution Log

The Execution Log displays live output captured from the current server process and uses the configured application timezone. It can help diagnose runtime and background-task failures. It contains only output captured since the process began; restarting starts a new capture.

For workspace settings, see [Workspace Config](workspace-config.md). For runtime settings, see [Application Config](app-config.md).
