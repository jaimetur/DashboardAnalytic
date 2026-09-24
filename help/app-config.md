# Application Config

Application Config stores application-wide runtime overrides. It is separate from Workspace Config, which groups the Report Templates Management, Operator Mappings and Vendor Mappings panels for the active workspace.

## Access and location

Open **Config → Application Config** from the main navigation at `/application-config`. The page is available to `user-editor`, `admin` and `super-admin` roles. `user-viewer` accounts do not have access. Application Config applies across workspaces; it does not change workspace-owned templates or mapping groups.

Persisted values are stored in the application database and take precedence over environment and Docker settings until changed. Use environment variables for deployment paths and secrets; Application Config does not replace those deployment settings.

## Runtime settings

- **IANA Timezone** controls displayed timestamps and newly stored local timestamps. Choose a name such as `Europe/Madrid`.
- **Report Chart Renderer** selects `dashboard-canvas` or the legacy `pil` renderer.
- **Chromium Executable** optionally selects an executable browser for Canvas rendering. Leave it empty to use the deployment setting or automatic detection.
- **Ignore event time filtering** ignores date and template conditions based on `Event_Start_Time` or `Event_End_Time`.
- **Maximum simultaneous tasks** sets the requested background task limit from 1 to 32. The effective server limit is capped at four and reserves one logical CPU for interactive requests.

Select **Save Configuration** to persist the values. Saving restarts the shared Canvas renderer so later charts use the selected renderer and browser.

See [Deployment Configuration](configuration.md) for environment variables, storage roots, Docker settings and bootstrap accounts. See [Workspace Config](workspace-config.md) for settings and management panels owned by an active workspace.
