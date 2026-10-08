# Application Config

Application Config stores application-wide runtime overrides. It is separate from Workspace Config, which groups the Report Templates, Main Cities, Mappings & Reference Data and scoring methodology panels for the active workspace.

> [!IMPORTANT]
> **Application-wide settings.** Saved values affect every workspace and take precedence over the corresponding environment defaults.

> [!TIP]
> **Choose the right configuration page.** Use Workspace Config for templates, Main Cities, chart mappings and scoring methodologies.

## Access and location

Open **Config → Application Config** from the main navigation at `/application-config`. The page is available to `user-editor`, `admin` and `super-admin` roles. `user-viewer` accounts do not have access. Application Config applies across workspaces; it does not change workspace-owned templates or mapping groups.

Persisted values are stored in the application database and take precedence over environment and Docker settings until changed. Use environment variables for deployment paths and secrets; Application Config does not replace those deployment settings.

## Runtime settings

- **IANA Timezone** controls displayed timestamps and newly stored local timestamps. Choose a name such as `Europe/Madrid`. Without it, or the `TZ` environment variable, the server's own timezone is used (UTC when the server has none).
- **Report Chart Renderer** selects `dashboard-canvas` or the legacy `pil` renderer.
- **Chromium Executable** optionally selects an executable browser for Canvas rendering. Leave it empty to use the deployment setting or automatic detection.
- **Ignore event time filtering** ignores date and template conditions based on `Event_Start_Time` or `Event_End_Time`.
- **Maximum simultaneous tasks** sets the requested background task limit from 1 to 32. The effective server limit is capped at four and reserves one logical CPU for interactive requests.

Select **Save Configuration** to persist the values. Saving restarts the shared Canvas renderer so later charts use the selected renderer and browser.

## Email Delivery

The **Email Delivery** panel configures the SMTP server that [Reporting](reporting.md) jobs use to send their artifacts. It is available to the same roles as the rest of Application Config.

| Field | Meaning |
| --- | --- |
| SMTP Server, Port | Mail server and port, for example `smtp.example.com` and `587` |
| Encryption | STARTTLS (usually port 587), SSL/TLS (usually 465) or none |
| Username, Password | Optional SMTP authentication. Leave the password empty to keep the saved one, or the `SMTP_PASSWORD` deployment value |
| Sender Address, Sender Name | The `From` of every report email |
| Attachment Size Limit (MB) | A run whose attachments exceed this total fails instead of being rejected by the mail server |

Select **Save Email Delivery**, then **Send Test Email** to check the settings. The deployment variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_FROM_NAME` and `SMTP_MAX_ATTACHMENTS_MB` provide defaults; saved values take precedence.

> [!WARNING]
> **The SMTP password is stored in the application database.** Configuration exports, transfers and backups include it. Use the `SMTP_PASSWORD` deployment variable instead if it must not leave the server.

See [Deployment Configuration](configuration.md) for environment variables, storage roots, Docker settings and bootstrap accounts. See [Workspace Config](workspace-config.md) for settings and management panels owned by an active workspace.
