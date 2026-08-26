<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="Dashboard Analytic logo" width="660">
</p>

# Dashboard Analytic

Dashboard Analytic is a multi-user web workspace for ingesting CDR-style datasets, profiling them automatically, extracting KPI-ready metrics, visualizing distributions and comparisons, and exporting the resulting analysis to Word or PowerPoint.

## What the tool does today

- Uploads `CSV`, `XLS`, `XLSX`, and `XLSM` datasets from the web UI
- Detects CDR workbook structure automatically, including multi-sheet operator workbooks
- Classifies imported datasets as `CDR-Voice`, `CDR-Speech`, `CDR-Data`, `Multivendor Mapping`, or `Other`
- Normalizes common dimensions such as market, period, operator, region, vendor, session type, direction, technology, and source sheet
- Extracts reusable base metrics such as setup time, duration, quality score, throughput, latency, jitter, packet loss, and handovers
- Builds dataset profiles and stores their status, progress, filter options, default metrics, and KPI snapshot in SQLite
- Shows a `Data Processing Queue` with dataset status, progress, and retry actions
- Opens the workspace immediately from cached metadata, without forcing a full dataset reload on every page refresh
- Applies adaptive filters and loads charts or tables only when the user requests `Update Dashboard`
- Exports the active dashboard context to Word or PowerPoint
- Exposes embedded `Readme` and `Changelog` viewers rendered from Markdown

## E2E PowerPoint Reporting

The top navigation separates the existing **E2E Dashboard** from **E2E PowerPoint Reporting**.

### Modules

- **NetCheck CDR Reports**: build a consistent template-based PowerPoint from one processed Data, Voice and Speech CDR. Select NSA or SA and, when needed, enrich Vodafone UK and Three UK results with their dedicated cell mappings.
- **Smart Orchestrator Logs Reports**: visible as the future reporting destination for processed Smart Orchestrator Log sources; automated log reporting is not implemented yet.

Workspace accepts NetCheck CDR workbooks, Smart Orchestrator Logs, VFUK Vodafone and 3UK Three Multivendor Mapping files. It proposes each input type from its filename, including a per-file review when files are uploaded in a batch, and persists the confirmed type before processing. For a multivendor report, upload separate **VFUK Vodafone UK** and **3UK Three UK** mapping files through Data Ingestion first. They become selectable in Reporting only when the report scope is `Multivendor`. Vendor assignment follows the provided Vodafone/Three formula, including Vodafone's Ericsson/null mixed-vendor exception. PPT templates are shipped in `assets/templates/` and can be overridden with `APP_REPORTING_TEMPLATE_DIR`. The active NSA/SA slide catalogues are stored in `assets/ppt-slides-catalog/`; administrators can export, edit and import them to control the rendered slide title, optional subtitle and chart layout.

### NetCheck CDR Reports workflow

1. Upload the three NetCheck workbooks (Data, Voice and Speech) in **Workspace** and wait until each one is marked `Processed`.
2. Upload both Multivendor Mapping workbooks (one **VFUK** file for Vodafone UK and one **3UK** file for Three UK) when a multivendor report is required.
3. Open **E2E PowerPoint Reporting → NetCheck CDR Reports**.
4. Select exactly one processed CDR for each required input type.
5. Choose `NSA` or `SA`. NSA sessions are selected when the available RAT field contains `ENDC`; SA sessions are selected when it contains `NR`.
6. Choose `Single-vendor` or `Multivendor`. The mapping selectors are shown only for multivendor; select one processed VFUK mapping for Vodafone UK and another processed 3UK mapping for Three UK.
7. Generate the PowerPoint report. The run stores its selected datasets, technology, scope, mapping and template in SQLite for auditability.

The report starts from `Template_CDR_NSA_analysis.pptx` or `Template_CDR_SA_analysis.pptx`. Its layout and non-automated scoring/gap slides are retained. Automated CDR slides receive charts calculated from the persisted CDR rows, while commentary text boxes are cleared for analyst input.

### Multivendor calculation

For Vodafone UK and Three, the report takes the first and last Global CI from the available CDR `Cell_ID_A`, `Cell_IDs_A` or `Cell_ID` field. Vodafone values are resolved only with the VFUK mapping and Three values only with the 3UK mapping. When a VFUK mapping is processed, Workspace materialises a `GCID` column for its `4G` rows as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied hexadecimal Excel formula; it also materialises the existing `5G` convention as `gNodeB ID × 4096 + Local Cell ID`. A 3UK mapping materialises the same `GCID` value as its `Cid__ECI` (or `CId___ECI`) source field. Mapping previews show every source column, with `GCID` first and highlighted; the VFUK preview is deliberately limited to a selectable `4G` or `5G` sheet. O2 and EE retain the operator label because they have no multivendor segmentation in this workflow.

- Vodafone: identical first/last vendor produces `Vodafone_<vendor>`; the Ericsson/null and differing-vendor cases follow the supplied formula and resolve to `Vodafone_Mixed Vendor` or `Vodafone_Other Vendor`.
- Three: identical first/last vendor produces `3_<vendor>`; all other combinations produce `3_Mixed Vendor`.

## Current UI workflow

1. Open the web workspace and sign in
2. Upload a source file in `Data Ingestion`
3. The dataset is queued, processed, and profiled automatically
4. The queue updates the processing state and stores the resulting profile in the database
5. Select a processed dataset in `Select Dataset`
6. The dashboard opens instantly from cached metadata
7. Use `Adaptive Filters` and press `Update Dashboard` to compute the full analysis
8. Review KPI cards, scorecards, charts, and aggregated tables
9. Export the current dashboard analysis to Word or PowerPoint if needed, or open **E2E PowerPoint Reporting** to create a template-backed CDR report

## Supported dataset behavior

### Automatic ingestion

- `XLSM` CDR workbooks are supported directly
- `Multivendor_Mapping` workbooks are recognized and retained as selectable mapping datasets for reporting
- Known summary sheets such as `MASTER`, `RANKING`, and similar non-data tabs are ignored
- Operator sheets are concatenated when needed
- Duplicate uploads of the same stored file are reused instead of creating a new dataset row
- Failed or stuck datasets can be retried from the queue or the selected dataset panel

### Dataset profiling

Each processed dataset stores:

- processing status and progress
- dataset kind
- row and column counts
- default metric
- default aggregation
- available metrics
- available aggregations
- adaptive filter values
- summary payload
- cached KPI snapshot

### Analytics

The dashboard currently includes:

- KPI cards
- percentile scorecard
- CDF curve
- comparison chart by aggregation
- processed metrics table

Voice, speech, and data datasets expose different KPI mixes based on the normalized columns available in the source.

## Performance model

The workspace is intentionally split into two phases:

- `cached open`: the dataset workspace opens from metadata already stored in SQLite
- `on-demand analysis`: charts and tables are calculated only when `Update Dashboard` is triggered

Additional analysis caching is applied per dataset file, metric, and filter combination. This avoids re-reading the same dataset on repeated refreshes of the same analytical view.

This does not replace long-term scalable storage or pre-aggregated analytics yet. It is a pragmatic cache layer for the current application model.

## Authentication and roles

Supported roles:

- `admin`
- `user`

Default local accounts:

- `admin / admin123`
- `demo / demo123`

The `admin` panel currently provides:

- user creation
- user listing
- dataset listing
- audit log inspection

## Embedded documentation

The top navigation exposes:

- `Readme`
- `Changelog`

Both open in a new tab and render Markdown inside the application through the same document-viewer pattern used in the related PhotoMigrator project.

## Local development

### Requirements

- Python `3.11+`
- `pip`

### Run from source

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn src.DashboardAnalytic:app --reload --port 7279
```

Open:

```text
http://127.0.0.1:7279
```

### Run tests

```bash
pytest -q
```

## Configuration model

Environment variables control deployment paths and runtime secrets. Version and release date do not come from `.env`; they are defined in [`src/version.py`](src/version.py).

Important runtime variables:

- `APP_PORT`
- `APP_SECRET_KEY`
- `APP_ADMIN_USERNAME`
- `APP_ADMIN_PASSWORD`
- `APP_DATABASE_PATH`
- `APP_INPUT_DIR`
- `APP_OUTPUT_DIR`
- `APP_EXPORT_DIR`
- `APP_REPORTING_TEMPLATE_DIR`
- `HOST_CONFIG_DIR`
- `HOST_DATA_DIR`
- `IMAGE_REPOSITORY`
- `IMAGE_TAG`
- `CONTAINER_NAME`

The provided Docker `.env` file is intended for deployment-level configuration, not for application versioning.

## Docker deployment

### Development compose

Use the development compose only for local development. It mounts `src/` and enables reload mode.

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

### Production compose

The production compose file is designed to pull a published Docker image instead of building locally:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d
```

Current production compose behavior:

- uses `${IMAGE_REPOSITORY}:${IMAGE_TAG}`
- uses `pull_policy: always`
- persists database and data directories through mounted volumes

## Docker Hub and GitHub Actions

The repository includes GitHub Actions workflows for:

- unit tests
- Docker image build and push
- source bundle packaging

Docker image publication behavior:

- `push` to `main` publishes a fresh image
- `push` of a git tag like `v0.1.0` publishes a Docker tag like `0.1.0`
- push to Docker Hub only happens if the repository secrets are configured

Required GitHub repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` or `DOCKERHUB_PASSWORD`

Current Docker image naming:

```text
${DOCKERHUB_USERNAME}/dashboard-analytic
```

Recommended tags:

- `latest`
- `main`
- `0.1.0`

## Synology NAS / DockerHand deployment

For NAS deployment with DockerHand, use `docker/docker-compose.yml`, not the development compose.

Example `.env` values:

```env
APP_NAME=Dashboard Analytic
APP_PORT=7278
APP_SECRET_KEY=change-me-dashboard-analytic
APP_ADMIN_USERNAME=admin
APP_ADMIN_PASSWORD=admin123
APP_DATABASE_PATH=/app/config/app.db
APP_INPUT_DIR=/app/data/input
APP_OUTPUT_DIR=/app/data/output
APP_EXPORT_DIR=/app/data/exports

HOST_CONFIG_DIR=/volume1/docker/stacks/dashboardanalytic/config
HOST_DATA_DIR=/volume1/docker/stacks/dashboardanalytic/data

IMAGE_REPOSITORY=jaimetur/dashboard-analytic
IMAGE_TAG=latest
CONTAINER_NAME=dashboardanalytic
```

Recommended stack layout:

```text
/volume1/docker/stacks/dashboardanalytic/
  docker-compose.yml
  .env
  config/
  data/
    input/
    output/
    exports/
```

## Repository layout

- `src/`
  - FastAPI entrypoint
  - ingestion, analytics, exports, auth, repository layers
  - Jinja templates, CSS, and JS assets
- `tests/`
  - unit and lightweight integration coverage
- `docker/`
  - development and production compose files
  - Dockerfile
  - deployment `.env`
- `help/`
  - project documentation
- `config/`
  - SQLite database location in local runs
- `data/`
  - input, output, and export folders for local runs

## Main routes

- `/login`
- `/dashboard`
- `/dashboard/upload`
- `/dashboard/retry/{dataset_id}`
- `/dashboard/analyze`
- `/dashboard/export/word`
- `/dashboard/export/powerpoint`
- `/documents/view/readme`
- `/documents/view/changelog`
- `/admin`
- `/healthz`

## Current limitations

- dataset processing runs in background tasks inside the web process, not in an external worker
- progress is coarse-grained, not a true step-by-step backend pipeline
- analytics caching is in memory, not persisted as a long-lived analytical cache
- SQLite is enough for the current app, but not the final storage model for very large multi-user deployments
- Word and PowerPoint exports are functional, but not yet tied to a final branded reporting template system

## Recommended next steps

- move processing to a dedicated worker queue
- persist heavy analytical aggregates instead of recomputing them on demand
- improve large-scale storage strategy for massive dataset libraries
- add richer domain-specific KPI packs and report templates

## Remote repository

Expected Git remote:

```text
https://github.com/jaimetur/DashboardAnalytic.git
```
