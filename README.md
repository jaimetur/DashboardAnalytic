<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="Dashboard Analytic logo" width="320">
</p>

# Dashboard Analytic

Dashboard Analytic is a multi-user web workspace for ingesting CDR-style datasets, profiling them automatically, extracting KPI-ready metrics, visualizing distributions and comparisons, and exporting the resulting analysis to Word or PowerPoint.

## What the tool does today

- Uploads `CSV`, `XLS`, `XLSX`, and `XLSM` datasets from the web UI
- Detects CDR workbook structure automatically, including multi-sheet operator workbooks
- Classifies imported datasets as `CDR-Voice`, `CDR-Speech`, `CDR-Data`, `Multivendor Mapping — VFUK`, `Multivendor Mapping — 3UK`, `Smart Orchestrator Logs`, or `Other`
- Normalizes common dimensions such as market, period, operator, region, vendor, session type, direction, technology, and source sheet
- Extracts reusable base metrics such as setup time, duration, quality score, throughput, latency, jitter, packet loss, and handovers
- Builds dataset profiles and stores their status, progress, filter options, default metrics, and KPI snapshot in SQLite
- Shows a `Data Processing Queue` with dataset status, progress, and retry actions
- Opens the workspace immediately from cached metadata, without forcing a full dataset reload on every page refresh
- Applies adaptive filters and loads charts or tables only when the user requests `Update Dashboard`
- Exports the active dashboard context to Word or PowerPoint
- Provides read-only dataset previews in a separate tab, including row/column text filters and CDR-specific multi-select filters
- Exposes embedded Readme, Changelog and Help viewers rendered from Markdown

## E2E PowerPoint Reporting

The top navigation separates the existing **E2E Dashboard** from **E2E PowerPoint Reporting**.

### Modules

- **NetCheck CDR Reports**: build a template-based PowerPoint from one processed Data, Voice and Speech CDR. Select NSA or SA, stored Slides Templates and, when eligible, a multivendor scope based on vendors already mapped in Workspace.
- **Smart Orchestrator Logs Reports**: visible as the future reporting destination for processed Smart Orchestrator Log sources; automated log reporting is not implemented yet.

Workspace accepts NetCheck CDR workbooks, Smart Orchestrator Logs, VFUK Vodafone and 3UK Three Multivendor Mapping files. It proposes each input type from its filename, including a per-file review when files are uploaded in a batch, and persists the confirmed type before processing. When ready VFUK and/or 3UK mappings already exist, each CDR upload also offers its own optional mapping selectors: the most recent matching mapping is preselected, or **No Map Vendor Column** keeps the CDR unmapped. Either operator mapping can be applied independently. Mapping can also be run later from the CDR action; Reporting deliberately does not perform mapping itself. Vendor assignment follows the provided Vodafone/Three formula, including Vodafone's Ericsson/null mixed-vendor exception. Managed Slides Templates are stored in `assets/slides-templates/` and the PowerPoint master in `assets/ppt-templates/`; their locations can be overridden with `APP_SLIDES_TEMPLATES_DIR` and `APP_PPT_TEMPLATES_DIR`.

### NetCheck CDR Reports workflow

1. Upload the three NetCheck workbooks (Data, Voice and Speech) in **Workspace** and wait until each one is marked `Processed`.
2. If a multivendor report is required, upload the **VFUK** and/or **3UK** mapping workbooks first. When importing each CDR, select the required mapping(s) from its optional VFUK/3UK selectors, or use **Map Vendors** later from the queue. That dialog preselects the newest ready mapping of each type and can queue several unmapped CDRs together without blocking the workspace. Each CDR stores the calculated Vendor values.
3. Open **E2E PowerPoint Reporting → NetCheck CDR Reports**.
4. Select exactly one processed CDR for each required input type.
5. Choose `NSA` or `SA`. NSA sessions are selected when the available RAT field contains `ENDC`; SA sessions are selected when it contains `NR`.
6. Choose compatible Slides Templates and `Single-vendor` or `Multivendor`. Multivendor is enabled only when all three selected Data, Voice and Speech CDRs have a saved vendor mapping.
7. Generate the PowerPoint report. The run stores its selected datasets, technology, scope and Slides Template in SQLite for auditability. Generated filenames use `yyyymmdd-hhmm`.

All NSA, SA, single-vendor and multivendor reports use the single master/layout-only `assets/ppt-templates/Template_CDR_analysis.pptx`. The selected Slides Templates determine the technology-specific slide sequence, layouts and generated CDR charts; commentary placeholders remain blank for analyst input.

### Multivendor calculation and remapping

For Vodafone UK and Three, the report takes the first and last Global CI from the available CDR `Cell_ID_A`, `Cell_IDs_A` or `Cell_ID` field. Vodafone values are resolved only with the VFUK mapping and Three values only with the 3UK mapping. When a VFUK mapping is processed, Workspace materialises a `GCID` column for its `4G` rows as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied hexadecimal Excel formula; it also materialises the existing `5G` convention as `gNodeB ID × 4096 + Local Cell ID`. A 3UK mapping materialises the same `GCID` value as its `Cid__ECI` (or `CId___ECI`) source field. Mapping previews show every source column, with `GCID` first and highlighted; the VFUK preview is deliberately limited to a selectable `4G` or `5G` sheet. O2 and EE retain the operator label because they have no multivendor segmentation in this workflow.

- Vodafone: identical first/last vendor produces `Vodafone_<vendor>`; the Ericsson/null and differing-vendor cases follow the supplied formula and resolve to `Vodafone_Mixed Vendor` or `Vodafone_Other Vendor`.
- Three: identical first/last vendor produces `3_<vendor>`; all other combinations produce `3_Mixed Vendor`.
- O2/EE are retained only as report comparison operators; they are not written into the CDR Vendor field.
- **Clear Vendors** removes a previous mapping so the CDR can be mapped again using newer mapping files.

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
- `Multivendor_Mapping` workbooks are recognized as separate VFUK/3UK mappings and retained for CDR vendor mapping in Workspace
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

Only KPI-like numeric CDR fields are offered as Dashboard metrics; geographic coordinates, identifiers and other technical metadata are excluded. Voice, speech and data datasets expose different KPI mixes based on the normalized columns available in the source.

### Slides Templates and chart grouping

The bundled `Template_CDR_analysis.pptx` contains masters and named layouts but no source slides. The generator creates one new presentation slide for every distinct `Slide` number in the selected NSA or SA Slides Templates, in ascending order. Each automated template row defines one chart; rows sharing the same slide number fill the selected layout's chart placeholders in row-major order.

The CSV schema is: `Slide`, `Slide tittle`, `Slide Subtittle`, `Layout`, `Chart Tittle`, `CDR source`, `KPI`, `Chart type`, `Legend`, `Filters`, `Grouping_Rows` and `Grouping_Columns`. `Chart type` also supports `Title Slide` and `Transition Slide`. These structural rows use only the slide title, subtitle and named layout and cannot contain CDR, KPI, chart, legend, filter or grouping configuration.

`Grouping_Rows` controls the visible category hierarchy. `Grouping_Columns` controls comparison series and legend values; when it is empty, the renderer uses one `(all)` series and does not repeat the category in labels. For distribution charts, the final column grouping is the stack/bucket dimension. This contract applies consistently to CDF, scatter, vertical bars, stacked bars and tables. Administrators can import legacy compatible files: the application offers to convert their headings, splits legacy `Grouping`, and assigns an appropriate default layout from the number of charts on each slide.

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

The `admin` panel provides:

- user creation
- user listing
- dataset listing
- audit log inspection
- named NSA/SA template management, import conversion, default selection, duplication, deletion and export
- an in-browser template editor with contextual assistance for layouts, chart types, fields, legends, grouping and filter conditions

## Embedded documentation

The top navigation exposes:

- `Readme`
- `Changelog`
- `Help`

They render Markdown inside the application; Help also provides a numbered sidebar for its project-specific articles.

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
- `APP_SLIDES_TEMPLATES_DIR`
- `APP_PPT_TEMPLATES_DIR`
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
- Smart Orchestrator Logs reporting and scoring/GAP automation remain future work

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
