# Configuration

Dashboard Analytic separates application settings, storage roots and Docker deployment variables. Source installations can set the three storage roots in `storage-paths.conf`; real environment variables take precedence. Docker deployments normally keep all settings in `docker/.env`.

## Runtime settings

| Variable | Purpose | Default or typical value |
| --- | --- | --- |
| `APP_NAME` | Application-name setting retained by the runtime configuration. Current release branding remains Dashboard Analytic. | `Dashboard Analytic` |
| `APP_HOST` | Bind address used when launching `python src/main.py`. | `0.0.0.0` |
| `APP_PORT` | Source launcher port and production host port in Compose. | `7278` |
| `APP_DEV_PORT` | Development host port mapped to the container service. | `7279` |
| `APP_SECRET_KEY` | Signs authenticated session cookies. | A long private random value |
| `DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER` | Renderer for Reports, Chart Sets, previews and Dashboard exports. | `dashboard-canvas`; use `pil` only for the legacy painter |
| `DASHBOARD_ANALYTIC_CHROMIUM` | Optional explicit Chromium-family executable used by the server Canvas renderer. | Auto-detected supported browser |
| `TZ` | IANA timezone used by Docker and displayed/persisted timestamps. | `Europe/Madrid` |
| `IGNORE_EVENT_TIME_FILTERING` | When true, ignores date and template filters based on Event_Start_Time or Event_End_Time. | `false` |

## Config page

Administrators can use the **Config** tab beside Admin to persist runtime settings in the application database. Values saved there take precedence over Docker and environment variables, and apply to every workspace.

- **Timezone** accepts an IANA name such as `Europe/Madrid`. It controls displayed timestamps and newly stored local timestamps.
- **Report Chart Renderer** selects `dashboard-canvas` or the legacy `pil` renderer.
- **Chromium Executable** accepts an absolute executable path. Saving it restarts the shared Canvas renderer, so the next chart uses the selected browser.
- **Ignore event time filtering** ignores Dashboard, Dataset Analysis and template conditions based on `Event_Start_Time` or `Event_End_Time`. Use it when source timestamps are incomplete and must not exclude valid rows.

`0.0.0.0` is a server bind address, not a browser destination. When the application binds to it locally, open `http://127.0.0.1:7278` or `http://localhost:7278`. From another computer, use the server's reachable hostname or IP address and the published host port.

Always replace `APP_SECRET_KEY` outside local development. Changing it invalidates existing signed sessions.

## Storage roots

| Variable | Contains |
| --- | --- |
| `APP_CONFIG_DIR` | Global `application.db`: users, roles, workspace permissions, application state and transfer offers. |
| `APP_DATA_DIR` | Workspace registry and directories, uploads, generated output, Dashboard caches, map tiles, backup ZIPs and temporary transfer/export packages. |
| `APP_ASSETS_DIR` | Bundled PowerPoint masters used by report and Dashboard generation. |

Only these three variables are accepted in `storage-paths.conf`:

```text
APP_CONFIG_DIR = /srv/dashboard-analytic/config
APP_DATA_DIR = /srv/dashboard-analytic/data
APP_ASSETS_DIR = /srv/dashboard-analytic/assets
```

Relative paths are resolved from the project root. `~` and environment-variable references are expanded. If the file is absent, the defaults are `config/`, `data/` and `assets/` inside the project. Environment variables with the same names override the file, which lets Docker use `/app/config`, `/app/data` and `/app/assets` without editing a developer's local configuration.

The process needs read/write access to `APP_CONFIG_DIR` and `APP_DATA_DIR`, including permission to create SQLite WAL/SHM sidecars and atomic temporary files. `APP_ASSETS_DIR` only needs to be readable during ordinary operation.

## Code asset overrides

These advanced environment variables relocate application code assets and are not valid entries in `storage-paths.conf`:

| Variable | Default | Use |
| --- | --- | --- |
| `APP_TEMPLATE_DIR` | `src/web_interface/templates` | Jinja HTML templates. |
| `APP_STATIC_DIR` | `src/web_interface/static` | CSS, JavaScript, images and fonts served below `/static`. |

Ordinary source and Docker installations should retain these defaults. They are deployment overrides, not workspace storage locations.

## Docker settings

These values are consumed by Compose rather than by the Python application:

| Variable | Purpose |
| --- | --- |
| `IMAGE_REPOSITORY` | Published Docker image repository. |
| `IMAGE_TAG` | Image version to pull and run. |
| `CONTAINER_NAME` | Container name. |
| `HOST_CONFIG_DIR` | Host directory mounted at `/app/config`. |
| `HOST_DATA_DIR` | Host directory mounted at `/app/data`. |

Production maps `${APP_PORT}:7278`; development maps `${APP_DEV_PORT}:7278`. The application inside the container always listens on `0.0.0.0:7278`. `APP_ASSETS_DIR=/app/assets` points to assets bundled in the image, so the standard Compose files persist only config and data.

Use a pinned `IMAGE_TAG` when a production deployment must be reproducible. See [Docker Deployment](11-docker-deployment.md) for complete commands and upgrade checks.

## Persistence layout

The configured roots produce this high-level layout:

```text
APP_CONFIG_DIR/
└── application.db

APP_DATA_DIR/
├── workspaces/
│   ├── workspace-registry.db
│   └── <workspace>/
├── transfer-packages/
├── scheduled-backups/
└── .map-tiles-cache/

APP_ASSETS_DIR/
└── ppt-templates/
    └── Template_CDR_analysis.pptx
```

Report Templates are records in each workspace database. CSV files appear in export, transfer and backup ZIPs as their portable representation; no persistent template CSV directory is required.

The starter Auto-calculated Field definitions remain a code asset at `assets/default-calculated-dimensions.json`; changing `APP_ASSETS_DIR` currently relocates the PowerPoint master lookup only.

For the complete workspace, output and cache tree, see [Project Structure → Persistent data layout](12-project-structure.md#persistent-data-layout).

## Bootstrap accounts

A brand-new empty `application.db` creates these accounts once:

- `super / super123` — `super-admin`
- `admin / admin123` — `admin`
- `demo / demo123` — `user`

All three receive access to the `Default` workspace. Later restarts do not recreate deleted users, reset passwords or restore changed roles.

After first login:

1. Click the username badge.
2. Change every bootstrap password that will remain enabled.
3. Review roles and workspace access in Admin.
4. Store the session secret and deployment configuration in the approved secret-management system.

## Validation checklist

- `http://127.0.0.1:7278/healthz` responds locally, or the equivalent published host and port responds remotely.
- A file uploaded to `Default` remains after an application or container restart.
- Workspace Report Templates and Dashboard definitions remain available.
- The workspace size and cache size reflect the configured data root.
- Dashboard preparation can create `.dashboard-data-cache` in the workspace.
- `APP_CONFIG_DIR` and `APP_DATA_DIR` are included in infrastructure backups.
