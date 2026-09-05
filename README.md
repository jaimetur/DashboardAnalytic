<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="Dashboard Analytic logo" width="320">
</p>

# Dashboard Analytic

Dashboard Analytic is a multi-user web application for processing CDR datasets, exploring KPI performance, building charts and generating template-driven PowerPoint reports. Every workspace keeps its datasets, database and generated output isolated; users and Slides Templates are shared application configuration.

After login, the application opens the **Readme** tab by default.

## Capabilities

- Upload and process `CSV`, `XLS`, `XLSX` and `XLSM` files.
- Classify CDR-Data, CDR-Voice, CDR-Speech, Smart Orchestrator Logs and VFUK/3UK mapping files.
- Combine operator workbook sheets and materialise normalised reporting fields.
- Preview complete datasets with pagination and Excel-style column filters.
- Analyse one processed CDR in E2E Dashboard.
- Create temporary ad-hoc charts in Chart Builder.
- Generate NSA/SA PowerPoint reports and standalone Chart Sets.
- Edit shared Slides Templates with validation, assistance and chart previews.
- Track meaningful user/system events in App Logs.
- Export, import or transfer configuration, templates and workspaces.
- Manage workspace and global SQLite tables from the Admin interface.

## Modules and sections

### Workspace

Workspace owns data ingestion and workspace-local storage.

- **Workspaces Management**: create, open, close, rename, duplicate or remove workspaces; review disk usage and access.
- **Data Ingestion**: upload one or more source files and confirm each detected type.
- **Queue and Status**: monitor processing, preview data, open Dashboard, map/clear vendors, stop, retry or delete datasets.

### E2E Dashboard

E2E Dashboard analyses one ready Data, Voice or Speech CDR.

- **Dashboard Controls**: dataset, KPI, adaptive filters and aggregations.
- **Executive Dashboard**: context, sample counts, KPI cards and percentiles.
- **Charts and Scorecards**: CDF curves and grouped comparisons.
- **Processed Metrics**: filtered/aggregated results and Word/PowerPoint exports.

### E2E Reporting

E2E Reporting combines ready CDRs with a shared Slides Template.

- **Reporting module**: choose NetCheck CDR Reports or the future Smart Orchestrator Logs workflow.
- **NetCheck CDR Reports**: select Data, Voice and Speech campaigns, NSA/SA, template and Operator/Vendor Comparison.
- **Charts Panel**: browse report or standalone Chart Sets, open Interactive Preview, inspect filtered data and edit the source template when authorised.
- **Reports and Charts Jobs**: one table for both background job types, with job-specific open, download, stop, retry, relaunch and delete actions.

### Chart Builder

Chart Builder is the ad-hoc chart editor immediately after E2E Reporting in Help. It reuses Interactive Preview, filters sources by CDR Type, supports multiple processed datasets and creates temporary charts without modifying templates. See [Chart Builder Help](help/08-chart-builder.md) for examples.

### Chart Builder

Chart Builder reuses the shared Interactive Preview for ad-hoc analysis.

- Choose Data, Voice or Speech first.
- Select one or more processed datasets of that type.
- Configure title, chart type, KPI, filters, ordered Rows/Columns aggregations and legend.
- Preview changes without creating a report or altering a template.

### App Logs

- Filter by User, Executed by, date, type and action.
- Distinguish the initiating user from automatic `system` execution.
- Refresh manually or automatically every five seconds.
- Review authentication, ingestion, processing, generation and administration events.

### Admin

- **Create user / Users**: account, role, password, status and workspace access management.
- **Slides Templates Management**: create, import, duplicate, rename, export, delete and set defaults.
- **Slides Template Editor**: validated grid editing, cell assistance, Filter Builder and shared Chart Preview.
- **Export / Import**: portable ZIP jobs, Full Environment workspace selection, server-to-server transfer and recovered packages.
- **Database Management**: grouped global/workspace tables, server-side filters, editing and cleanup.
- **Datasets Management**: inspect and rename workspace datasets.

### Documentation tabs

- **Readme**: this concise product and deployment guide.
- **Changelog**: versioned release notes.
- **Help**: detailed task and technical documentation.

See [Product overview](help/01-overview.md) for a detailed tour of every module and [Technical considerations](help/02-technical-considerations.md) for calculation, normalisation, mapping, filtering, storage and performance rules.

## Quick workflow

1. Sign in and open or create a workspace.
2. Upload the required source files in Workspace.
3. Confirm their types and wait for **Processed**.
4. Optionally map VFUK/3UK vendor data.
5. Use Dashboard, Chart Builder or Reporting.
6. Review long-running work in **Reports and Charts Jobs**.
7. Check App Logs if an operation fails.

## Requirements

- Python 3.11 or newer for source development.
- Docker Engine with Compose for the recommended service deployment.
- Writable persistent configuration and data directories.

## Run from source

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn src.DashboardAnalytic:app --reload --port 7279
```

Open `http://127.0.0.1:7279`.

Run tests with:

```bash
pytest -q
```

## Configuration

Local storage roots can be set in [`storage-paths.conf`](storage-paths.conf). Environment variables override that file.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Application name shown in the UI. |
| `APP_PORT` | Production HTTP port; the standard deployment uses `7278`. |
| `APP_DEV_PORT` | Development service port. |
| `APP_SECRET_KEY` | Private session-signing secret. |
| `APP_CONFIG_DIR` | Global database and shared Slides Templates. |
| `APP_DATA_DIR` | Workspace registry, workspaces and transfer packages. |
| `APP_ASSETS_DIR` | Bundled assets and PowerPoint masters. |
| `TZ` | Container timezone, for example `Europe/Madrid`. |
| `HOST_CONFIG_DIR` | Host path mounted as persistent configuration. |
| `HOST_DATA_DIR` | Host path mounted as persistent data. |
| `IMAGE_REPOSITORY` | Published container repository. |
| `IMAGE_TAG` | Container tag to deploy. |
| `CONTAINER_NAME` | Production container name. |

Do not commit real secrets or customer data. Change the bootstrap passwords after the first deployment.

## Default accounts

A new empty configuration database creates these accounts once:

| Username | Initial password | Role |
| --- | --- | --- |
| `super` | `super123` | `super-admin` |
| `admin` | `admin123` | `admin` |
| `demo` | `demo123` | `user` |

All three initially have access to the `Default` workspace. Accounts are not recreated or reset on later starts.

## Docker deployment

### Production

Production pulls the configured published image and persists `config/` and `data/` on the host.

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --pull always
```

Key behaviour:

- Uses `${IMAGE_REPOSITORY}:${IMAGE_TAG}`.
- Pulls the selected tag on start.
- Supports native `linux/amd64` and `linux/arm64` images.
- Includes `assets/ppt-templates/Template_CDR_analysis.pptx` in the image.
- Mounts configuration and workspace data outside the container.
- Exposes port `7278` by default.

Check status and logs:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml ps
docker compose --env-file docker/.env -f docker/docker-compose.yml logs -f
```

### Development

The development stack mounts source code and enables reload mode:

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

### Example production environment

```env
APP_NAME=Dashboard Analytic
APP_PORT=7278
APP_SECRET_KEY=replace-with-a-long-private-value
APP_CONFIG_DIR=/app/config
APP_DATA_DIR=/app/data
APP_ASSETS_DIR=/app/assets
TZ=Europe/Madrid

HOST_CONFIG_DIR=/volume1/docker/stacks/dashboardanalytic/config
HOST_DATA_DIR=/volume1/docker/stacks/dashboardanalytic/data

IMAGE_REPOSITORY=jaimetur/dashboard-analytic
IMAGE_TAG=latest
CONTAINER_NAME=dashboardanalytic
```

### Persistent layout

```text
<deployment-root>/
├── config/
│   ├── application.db
│   └── slides-templates/
└── data/
    ├── transfer-packages/
    └── workspaces/
        ├── workspace-registry.db
        └── <workspace>/
            ├── <workspace>.db
            ├── input/
            └── output/
                ├── reports/
                └── charts/
```

Back up both persistent roots. Backing up only the container does not preserve application state.

### Safe update

1. Back up `HOST_CONFIG_DIR` and `HOST_DATA_DIR`.
2. Set the intended `IMAGE_TAG`.
3. Pull and restart the Compose stack.
4. Sign in and confirm users, workspace access and templates.
5. Open a workspace and verify its datasets.
6. Generate a small Chart Set or report before normal production use.

## GitHub Actions and images

The repository workflows run tests, build/push images and package source bundles.

- Version tags publish the corresponding image tag.
- Successful builds refresh `latest` according to workflow rules.
- Pushes to `main` refresh the `main` tag.
- Published manifests include AMD64 and ARM64 variants.
- Build cache accelerates unchanged dependency layers while source layers are invalidated by the current commit.

Required repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` or `DOCKERHUB_PASSWORD`

Inspect a published manifest:

```bash
docker buildx imagetools inspect ${DOCKERHUB_USERNAME}/dashboard-analytic:latest
```

## Repository layout

```text
DashboardAnalytic/
├── src/                    # FastAPI application, modules and browser UI
├── tests/                  # Unit and integration tests
├── docker/                 # Dockerfiles, Compose and environment settings
├── assets/ppt-templates/   # PowerPoint master/layout file
├── config/                 # Global database and Slides Templates
├── data/workspaces/        # Workspace registry and isolated workspace data
├── help/                   # Detailed in-app documentation
├── README.md
└── CHANGELOG.md
```

## Current limitations

- Background processing runs in the web process rather than an external worker service.
- In-memory analytical caches do not survive a process restart.
- SQLite is the current persistence model and may not suit very large concurrent deployments.
- Smart Orchestrator Logs reporting is visible but not implemented.
- Scoring and GAP automation remain planned work.

## More documentation

- [Help home](help/00-help.md)
- [Product overview](help/01-overview.md)
- [Technical considerations](help/02-technical-considerations.md)
- [Configuration](help/03-configuration.md)
- [Web interface](help/04-web-interface.md)
- [Data ingestion](help/05-data-ingestion.md)
- [E2E Dashboard](help/06-e2e-dashboard.md)
- [E2E Reporting](help/07-e2e-reporting.md)
- [Chart Builder](help/08-chart-builder.md)
- [Administration](help/09-administration.md)
- [Docker deployment](help/10-docker-deployment.md)
- [Project structure](help/11-project-structure.md)
- [Roadmap](help/12-roadmap.md)
