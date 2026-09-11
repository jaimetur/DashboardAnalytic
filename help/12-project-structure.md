# Project structure

## Source tree

```text
DashboardAnalytic/
├── src/
│   ├── DashboardAnalytic.py
│   ├── modules/
│   ├── utils/
│   └── web_interface/
│       ├── templates/
│       └── static/
├── tests/
├── docker/
├── assets/ppt-templates/
├── config/
├── data/
├── help/
├── README.md
└── CHANGELOG.md
```

## Application layer

- `src/DashboardAnalytic.py`: FastAPI routes, page composition, background job orchestration and shared UI payloads.
- `src/modules/repository.py`: SQLite schemas, migrations and persistence operations.
- `src/modules/cdr_reporting.py`: Report Template parsing, filtering, aggregation and reporting contracts.
- Reporting/rendering modules: chart PNG and PowerPoint generation.
- `src/web_interface/templates/`: Jinja pages and browser behaviour.
- `src/web_interface/static/`: shared CSS, JavaScript and images.

## Persistent configuration

```text
config/
└── application.db
```

`application.db` stores global state such as users, workspace permissions and transfer offers.

## Persistent workspace data

```text
data/workspaces/
├── workspace-registry.db
└── <workspace>/
    ├── <workspace>.db
    ├── slides-templates/
    ├── input/
    └── output/
        ├── reports/
        └── charts/
```

The workspace database stores:

- dataset records and profiles;
- materialised dataset rows;
- combined Data/Voice/Speech reporting rows;
- audit events;
- unified Report and Chart Set jobs.
- Auto-calculated Field definitions;
- Report Template metadata in `report_templates`.

## Reporting assets

- `assets/ppt-templates/Template_CDR_analysis.pptx` supplies masters and layouts.
- Workspace CSV Report Templates define slide order, layout, charts, filters, aggregations and legends.
- Generated report charts stay beside their PPTX under `output/reports/`.
- Standalone Chart Sets stay under `output/charts/`.

## Documentation

- `README.md`: concise product, setup and deployment guide.
- `CHANGELOG.md`: versioned changes.
- `help/00-help.md`: Help index.
- `help/01-overview.md`: detailed product tour.
- `help/02-technical-considerations.md`: calculation and architecture rules.
- Remaining numbered files: focused operational guides.

The in-app Help navigation is explicitly curated in `DashboardAnalytic.py`; renaming an article requires updating that list and its tests.

## Testing

- `tests/test_app.py`: routes, UI, admin, documentation and integration behaviour.
- `tests/test_cdr_reporting.py`: filter/template/report/chart contracts.
- Other test modules cover workspaces and domain-specific components.

Run:

```bash
pytest -q
```

Keep databases, uploaded customer files and generated output out of source control.

## Template-driven dashboards

`src/modules/e2e_dashboards.py` registers Dashboard persistence, SQL selection, chart PNG and filtered-data endpoints. `e2e_dashboards.html`, `e2e_dashboards.js` and `e2e_dashboards.css` provide the workspace tab and synchronized overlays. Definitions are stored under `e2e_dashboards_v2` in workspace state; existing `e2e_dashboard_sets_v1` values migrate automatically. `dashboard_filter_selections` and `dashboard_filter_selection_rows` persist bounded filter metadata and compact row-key selections in the workspace database, while rendered images use the bounded `.dashboard-chart-cache` directory beside that database. Single-dataset analysis uses `datasets_analysis.html` and `/datasets-analysis`; legacy `/dashboard` endpoints remain compatibility aliases.
