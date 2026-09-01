<p align="center">
  <img src="src/web_interface/static/img/brand-mark.png" alt="Dashboard Analytic logo" width="320">
</p>

# Dashboard Analytic

Dashboard Analytic is a multi-user application for ingesting CDR-style datasets, profiling them automatically, visualising KPI analysis and producing dashboard or template-based PowerPoint outputs. Work is isolated in named workspaces.

## What the tool does today

- Uploads `CSV`, `XLS`, `XLSX`, and `XLSM` datasets from the web UI
- Detects CDR workbook structure automatically, including multi-sheet operator workbooks
- Classifies imported datasets as `CDR-Voice`, `CDR-Speech`, `CDR-Data`, `Multivendor Mapping — VFUK`, `Multivendor Mapping — 3UK`, `Smart Orchestrator Logs`, or `Other`
- Normalizes common dimensions such as market, period, operator, region, vendor, session type, direction, technology, and source sheet
- Extracts reusable base metrics such as setup time, duration, quality score, throughput, latency, jitter, packet loss, and handovers
- Builds dataset profiles and stores their status, progress, filter options, default metrics, and KPI snapshot in SQLite
- Shows a `Data Processing Queue` with dataset status, progress, and retry actions
- Keeps every workspace's datasets, SQLite database and input/export files isolated
- Opens datasets from cached metadata, without forcing a full dataset reload on every page refresh
- Applies adaptive filters and loads charts or tables only when the user requests `Update Dashboard`
- Exports the active dashboard context to Word or PowerPoint
- Provides read-only dataset previews in a separate tab, including Excel-style column filters and CDR-specific multi-select filters
- Lets administrators inspect, edit, filter and delete rows in the active workspace database
- Exposes embedded Readme, Changelog and Help viewers rendered from Markdown

## E2E PowerPoint Reporting

The top navigation separates the existing **E2E Dashboard** from **E2E PowerPoint Reporting**.

### Modules

- **NetCheck CDR Reports**: build a template-based PowerPoint from one or more processed Data, Voice and Speech CDRs. Select NSA or SA, stored Slides Templates and, when eligible, a multivendor scope based on vendors already mapped in Workspace.
- **Smart Orchestrator Logs Reports**: visible as the future reporting destination for processed Smart Orchestrator Log sources; automated log reporting is not implemented yet.

Workspace accepts NetCheck CDR workbooks, Smart Orchestrator Logs, VFUK Vodafone and 3UK Three Multivendor Mapping files. It proposes each input type from its filename, supports per-file review for a batch and persists the confirmed type before processing. When ready VFUK and/or 3UK mappings already exist, CDR uploads also offer optional mapping selectors; mapping can also be run later from the CDR action. Reporting deliberately never maps CDRs itself. Vendor assignment follows the Vodafone/Three formula, including Vodafone's Ericsson/null mixed-vendor exception. Slides Templates are shared application configuration in `config/slides-templates/`; their metadata and global user accounts are stored in `config/application.db`, independently of workspaces. The shared PowerPoint master is in `assets/ppt-templates/`.

### NetCheck CDR Reports workflow

1. Upload the three NetCheck workbooks (Data, Voice and Speech) in **Workspace** and wait until each one is marked `Processed`.
2. If a multivendor report is required, upload the **VFUK** and/or **3UK** mapping workbooks first. When importing each CDR, select the required mapping(s) from its optional VFUK/3UK selectors, or use **Map Vendors** later from the queue. That dialog preselects the newest ready mapping of each type and can queue several unmapped CDRs together without blocking the workspace. Each CDR stores the calculated Vendor values.
3. Open **E2E PowerPoint Reporting → NetCheck CDR Reports**.
4. Select one or more processed CDRs for each required input type. CDRs of the same type are read from the shared reporting table, retaining campaign values for comparisons.
5. Choose `NSA` or `SA`. NSA sessions are selected when the available RAT field contains `ENDC`; SA sessions are selected when it contains `NR`.
6. Choose compatible Slides Templates and `Single-vendor` or `Multivendor`. Multivendor is enabled only when all three selected Data, Voice and Speech CDRs have a saved vendor mapping.
7. Generate the PowerPoint report. It is queued as a persistent background job, so it continues after leaving Reporting or signing out. **Generated Reports Jobs** shows the complete persisted history with ID, date, report name, selected datasets, template, slide count, type, multivendor state, creator, status and progress; ready reports can be downloaded, opened or deleted. New PPTX files are stored under the active workspace's `output/reports` directory, while older jobs remain accessible from the former `exports` location. The run stores its selected datasets, technology, scope and Slides Template in SQLite for auditability.

All NSA, SA, single-vendor and multivendor reports use the single master/layout-only `assets/ppt-templates/Template_CDR_analysis.pptx`. The selected Slides Templates determine the technology-specific slide sequence, layouts and generated CDR charts; commentary placeholders remain blank for analyst input.

Workspace preserves a dataset's original upload date when the same stored file is processed again. The separate **Updated** value reflects the latest processing activity, while the original upload date determines Workspace ordering and every automatic “latest dataset” selection for CDR and Multivendor Mapping controls.

When a report combines historical campaigns, reporting normalises known UK operator aliases in memory before template filters and groupings run. For example, `Vodafone`/`Vodafone UK` become `Vodafone`; `O2(UK)`/`o2 - de` become `O2`; `3`/`Three`/`three(uk)` become `3`; and EE variants become `EE`. This report-only step also makes `Operator IN (Vodafone, O2, 3, EE)` match the corresponding historical spellings; it never changes the stored CDR data.

### Multivendor calculation and remapping

For Vodafone UK and Three, the report takes the first and last Global CI from the available CDR `Cell_ID_A`, `Cell_IDs_A`, `Cell_ID`, `Global CI`, `GCID`, `GCI`, `CGI` or `ECI` field; case and separator variations are accepted. Vodafone values are resolved only with the VFUK mapping and Three values only with the 3UK mapping. When a VFUK mapping is processed, Workspace materialises a `GCID` column for its `4G` rows as `eNodeB ID × 256 + Local Cell ID`, equivalent to the supplied hexadecimal Excel formula; it also materialises the existing `5G` convention as `gNodeB ID × 4096 + Local Cell ID`. A 3UK mapping materialises the same `GCID` value as its `Cid__ECI` (or `CId___ECI`) source field. Mapping previews show every source column, with `GCID` first and highlighted; the VFUK preview is deliberately limited to a selectable `4G` or `5G` sheet. O2 and EE retain the operator label because they have no multivendor segmentation in this workflow.

- Vodafone: identical first/last vendor produces `Vodafone_<vendor>`; the Ericsson/null and differing-vendor cases follow the supplied formula and resolve to `Vodafone_Mixed Vendor` or `Vodafone_Other Vendor`.
- Three: identical first/last vendor produces `3_<vendor>`; all other combinations produce `3_Mixed Vendor`.
- O2/EE are retained only as report comparison operators; they are not written into the CDR Vendor field.
- **Clear Vendors** removes a previous mapping so the CDR can be mapped again using newer mapping files. Like mapping, it can process several CDRs through the background Workspace queue.

## Current UI workflow

1. Sign in and select the workspace to open. The most recently opened workspace is preselected.
2. In **Workspace Management**, create, open, close, rename, duplicate or remove workspaces as required. Closing the active workspace hides ingestion and queue operations and disables Dashboard and Reporting until one is opened.
3. Upload a source file in `Data Ingestion`
4. The dataset is queued, processed, and profiled automatically
5. The queue updates the processing state and stores the resulting profile in the active workspace database
6. Select a processed CDR in `Select Dataset`
7. Use `Adaptive Filters` and press `Update Dashboard` to compute the full analysis
8. Review KPI cards, scorecards, charts, and aggregated tables
9. Export the current dashboard analysis to Word or PowerPoint if needed, or open **E2E PowerPoint Reporting** to create a template-backed CDR report

An import captures its workspace database when it is queued. It therefore continues in the server after closing that workspace or signing out; reopening the workspace later shows its final status.

## Admin Import/Export

Administrators can create portable ZIP packages from **Admin → Import/Export**. `Only Config` exports application configuration without the local workspace registry. `Config + Slides Templates` additionally includes the shared CSV templates. `Workspace: <name>` exports that workspace's database, uploaded files and generated exports. `Full Environment` combines configuration, templates and all workspaces, rebuilding the destination registry from the imported workspaces instead of reusing source-machine paths. Exports are prepared as server-side jobs in `data/transfer-packages/`; once ready, the browser downloads the ZIP directly instead of loading it into memory. Temporary packages expire after 24 hours. Before import, the application inspects the package and requires confirmation showing whether configuration, templates or same-named workspaces will be overwritten. An active workspace must be closed before it can be replaced.

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

The CSV schema is: `Slide`, `Slide tittle`, `Slide Subtittle`, `Layout`, `Chart Tittle`, `CDR source`, `KPI`, `Chart type`, `Filters`, `Rows Aggregation`, `Column Aggregation`, `Legend` and `Legend Position`. `Legend Position` accepts `Top`, `Bottom`, `Left` or `Right`: top/bottom draw a horizontal legend row, while left/right draw a vertical legend column. Blank values default to `Top`. `Chart type` also supports `Title Slide` and `Transition Slide`. These structural rows use only the slide title, subtitle and named layout and cannot contain CDR, KPI, chart, legend, filter or aggregation configuration.

`Rows Aggregation` controls the visible category hierarchy. `Column Aggregation` controls comparison series and legend values; when it is empty, the renderer uses one `(all)` series and does not repeat the category in labels. For distribution charts, the final column aggregation is the stack/bucket dimension. This contract applies consistently to CDF, scatter, vertical bars, stacked bars and tables. Administrators can import legacy compatible files: the application offers to convert their headings, splits legacy `Grouping`, and assigns an appropriate default layout from the number of charts on each slide.

## Performance model

The workspace is intentionally split into two phases:

- `cached open`: the dataset workspace opens from metadata already stored in SQLite
- `on-demand analysis`: charts and tables are calculated only when `Update Dashboard` is triggered

Additional analysis caching is applied per dataset file, metric, and filter combination. This avoids re-reading the same dataset on repeated refreshes of the same analytical view.

For reporting, processed CDR rows are also synchronised into one shared table per CDR type. This avoids repeatedly concatenating the same campaign files and lets each report load only the fields required by its Slides Template.

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
- Database Management for the active workspace, with paginated table browsing, server-side multi-value filtering, row editing and row deletion

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

[`storage-paths.conf`](storage-paths.conf) in the project root controls the local `APP_CONFIG_DIR`, `APP_DATA_DIR` and `APP_ASSETS_DIR` roots without editing Python. Environment variables take precedence, which keeps Docker and other deployments configurable. Databases and shared Slides Templates derive from the config root, PowerPoint masters from the assets root, and workspace data from the data root. Version and release date do not come from `.env`; they are defined in [`src/version.py`](src/version.py).

Important runtime variables:

- `APP_PORT`
- `APP_SECRET_KEY`
- `APP_ADMIN_USERNAME`
- `APP_ADMIN_PASSWORD`
- `APP_CONFIG_DIR`
- `APP_DATA_DIR`
- `APP_ASSETS_DIR`
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

The production compose file is designed to pull a published Docker image instead of building locally. Published images include the bundled `assets/ppt-templates/Template_CDR_analysis.pptx` master required for PowerPoint reports:

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
APP_CONFIG_DIR=/app/config
APP_DATA_DIR=/app/data
APP_ASSETS_DIR=/app/assets

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
    slides-templates/          # shared editable Slides Templates library
  data/
    workspaces/
      workspace-registry.db    # local workspace registry and active state
      <Workspace Name>/
        <Workspace Name>.db
        input/
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
  - application configuration and shared Slides Templates
- `data/`
  - workspace registry plus isolated workspace directories, databases and files

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
