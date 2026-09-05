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
- `src/modules/cdr_reporting.py`: Slides Template parsing, filtering, aggregation and reporting contracts.
- Reporting/rendering modules: chart PNG and PowerPoint generation.
- `src/web_interface/templates/`: Jinja pages and browser behaviour.
- `src/web_interface/static/`: shared CSS, JavaScript and images.

## Persistent configuration

```text
config/
├── application.db
└── slides-templates/
```

`application.db` stores global state such as users, workspace permissions, template metadata and transfer offers.

## Persistent workspace data

```text
data/workspaces/
├── workspace-registry.db
└── <workspace>/
    ├── <workspace>.db
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

## Reporting assets

- `assets/ppt-templates/Template_CDR_analysis.pptx` supplies masters and layouts.
- CSV Slides Templates define slide order, layout, charts, filters, aggregations and legends.
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
