# Project structure

## Repository tree

```text
DashboardAnalytic/
├── src/
│   ├── DashboardAnalytic.py
│   ├── main.py
│   ├── config.py
│   ├── version.py
│   ├── modules/
│   ├── utils/
│   └── web_interface/
│       ├── templates/
│       └── static/
├── assets/
│   ├── default-calculated-dimensions.json
│   └── ppt-templates/
├── docker/
├── help/
├── tests/
├── tools/
├── .github/workflows/
├── storage-paths.conf
├── pyproject.toml
├── requirements.txt
├── README.md
└── CHANGELOG.md
```

Runtime `config/` and `data/` directories use project-local defaults but are excluded from source control and Docker build context.

## Python application layer

- `src/main.py`: shared source, PyCharm and Docker launcher using `APP_HOST`, `APP_PORT` and the timestamped Uvicorn logging configuration.
- `src/DashboardAnalytic.py`: FastAPI application, page/API routes, workspace activation, shared background-task orchestration, Admin portability and classic Reporting jobs.
- `src/config.py`: environment and `storage-paths.conf` resolution.
- `src/version.py`: application version and release date shown by the UI.
- `src/modules/repository.py`: global/workspace SQLite schemas, migrations and persistence methods.
- `src/modules/workspaces.py`: workspace registry, lifecycle, path migration, duplication and deletion.
- `src/modules/ingestion.py`: workbook/CSV ingestion, CDR classification helpers and derived input fields.
- `src/modules/analytics.py`: single-dataset analytical calculations.
- `src/modules/exports.py`: Datasets Analysis Word and PowerPoint output.
- `src/modules/cdr_reporting.py`: Report Template parsing, filters, aggregations, chart contracts, map tiles and classic report rendering.
- `src/modules/e2e_dashboards.py`: Dashboard definitions, direct combined-CDR SQL selections, preview/model caches, live previews, filtered chart data and Dashboard PPT jobs.
- `src/modules/dashboard_canvas_renderer.mjs`: Node/Chromium-compatible Canvas rendering used for consistent interactive and exported charts.
- `src/modules/auth.py`: password and authentication helpers.
- `src/utils/`: chart, filesystem and font utilities shared by modules.

## Browser layer

- `src/web_interface/templates/`: Jinja pages for Workspace, Datasets Analysis, E2E Dashboards, E2E Reporting, Chart Builder, Admin, App Logs and document viewing.
- `src/web_interface/static/js/`: shared UI behaviour, common chart drawing and the E2E Dashboard client.
- `src/web_interface/static/css/`: application and module-specific styles.
- `src/web_interface/static/markdown_renderer.js`: in-app README, Changelog and Help rendering, including cross-document heading anchors.
- `src/web_interface/static/img/`: brand and interface images.

## Persistent data layout

```text
APP_CONFIG_DIR/
└── application.db

APP_DATA_DIR/
├── workspaces/
│   ├── workspace-registry.db
│   └── <workspace>/
│       ├── <workspace>.db
│       ├── .dashboard-cache-version.json
│       ├── .dashboard-data-cache/
│       │   ├── dashboard-previews/
│       │   ├── charts-canvas/
│       │   └── charts-pil/
│       ├── input/
│       └── output/
│           ├── reports/
│           ├── charts/
│           └── dashboards/
├── transfer-packages/
├── scheduled-backups/
└── .map-tiles-cache/
    └── openstreetmap/
```

Directories are created when their corresponding feature first needs them, so an unused workspace may contain only its database and basic input/output roots. SQLite can also create temporary `-wal` and `-shm` sidecars beside active databases.

### Global database

`APP_CONFIG_DIR/application.db` owns:

- users, roles and workspace access lists;
- global application state;
- server-transfer offers.

### Workspace registry

`APP_DATA_DIR/workspaces/workspace-registry.db` owns workspace IDs, display names, registered paths, lifecycle status and the active-workspace pointer. Registry paths are rewritten during portable import instead of preserving absolute paths from another server.

### Workspace database

Each `<workspace>.db` owns:

- dataset records, processing profiles and audit logs;
- individual materialised dataset-row tables and combined Data/Voice/Speech reporting tables;
- Auto-calculated Field definitions;
- complete database-backed Report Templates in `report_templates`;
- saved Dashboard definitions in workspace state;
- cached Dashboard selection metadata and bounded row identities;
- classic Report/Chart Set jobs in `generated_jobs`;
- Dashboard PowerPoint history in `dashboard_ppt_jobs`.

Report Templates become CSV files only inside portable export, transfer and backup packages.

### Regenerable Dashboard cache

`.dashboard-cache-version.json` records the application and cache-format signature. Opening a workspace deletes older incompatible cache versions and selection metadata. `.dashboard-data-cache` contains reusable preview manifests, Canvas chart models and legacy PIL artifacts. Dashboard rows remain only in the workspace's combined CDR tables. The cache can be cleared without removing datasets, Dashboard definitions, templates or generated jobs, and clearing it does not trigger an automatic rebuild.

### Generated output

- `output/reports/`: classic Report PPTX files and report chart assets.
- `output/charts/`: standalone Chart Sets.
- `output/dashboards/`: Dashboard PPTX files plus persistent PNG, tooltip and Canvas-model assets used by PowerPoint Generation Jobs and Charts Panel.

`transfer-packages/` holds temporary or recoverable portable packages. `scheduled-backups/` is the default Admin backup destination. `.map-tiles-cache/openstreetmap/` is a shared regenerable tile cache outside individual workspaces.

## Bundled assets

- `assets/ppt-templates/Template_CDR_analysis.pptx` supplies slide masters, named layouts and placeholders.
- `assets/default-calculated-dimensions.json` supplies initial Auto-calculated Field definitions where applicable.
- Workspace Report Templates supply slide/chart definitions and are documented in [Administration → Report Template reference](11-administration.md#report-template-reference).

## Documentation

- `README.md`: product summary, source quick start and deployment overview.
- `CHANGELOG.md`: versioned release history.
- `help/00-help.md`: in-app Help index.
- `help/01-overview.md`: product and module tour.
- `help/02-technical-considerations.md`: data interpretation, persistence, caching and job semantics.
- Remaining numbered Help files: focused operational and deployment guides.

The Help navigation order and labels are curated in `src/DashboardAnalytic.py`. Renaming an article requires updating that list, incoming links and related tests.

## Tests, tooling and delivery

- `tests/test_app.py`: routes, shared UI, Admin, documentation and integration behaviour.
- `tests/test_e2e_dashboards.py`: Dashboard definitions, filtering, caching, rendering and PPT jobs.
- `tests/test_cdr_reporting.py`: template, filter, chart and classic Reporting contracts.
- Other test modules cover analytics, exports, workspaces and workspace template isolation.
- `tools/`: maintenance/build helpers.
- `.github/workflows/`: automated tests, Docker publishing and source packaging.
- `docker/`: production/development Compose files, image definition and execution notes.

Run the complete suite from the repository root:

```bash
python -m pytest -q
```

Keep databases, uploaded customer files, generated output, cache files and secrets out of source control.
