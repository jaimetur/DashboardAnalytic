# Project structure

The project separates the FastAPI application, domain modules, browser assets, reporting templates and operational documentation.

```text
DashboardAnalytic/
├── src/
│   ├── DashboardAnalytic.py       # FastAPI routes and application wiring
│   ├── modules/                   # ingestion, analytics, exports, auth and persistence
│   ├── utils/                     # shared helpers
│   └── web_interface/             # Jinja templates, JavaScript and CSS
├── assets/ppt-templates/          # bundled master PowerPoint template
├── config/                        # application configuration, registry and template seed library
├── help/                          # Help-centre Markdown articles
├── tests/                         # automated tests
├── docker/                        # Compose definitions and environment configuration
├── data/workspaces/               # isolated workspace databases and files
└── README.md                      # project overview and quick start
```

## Key implementation areas

- **Routes and pages:** `src/DashboardAnalytic.py` exposes API and document/help routes; `src/web_interface/templates/` contains the application, reporting and Help views.
- **Reporting:** the reporting module loads processed CDR data, applies NSA/SA and persisted vendor logic, parses filters and row/column grouping from the selected Slides Templates, then fills the supplied PowerPoint layouts. The PowerPoint master is kept in `assets/ppt-templates/` so deployments do not depend on a user desktop.
- **Workspaces and persistence:** `config/workspace-registry.db` stores only the local workspace catalogue and active-state information. Each workspace lives at `data/workspaces/<Workspace Name>/`, with a same-named SQLite database plus `input/` and `exports/` directories. Dataset records, individual materialised rows and shared reporting rows are isolated in that database.
- **Slides Templates configuration:** `config/slides-templates/` is the shared editable library used by all workspaces. Its `default/nsa/`, `default/sa/` and `library/` folders contain the executable report CSVs. The Admin editor and importer use this schema as the chart contract.
- **Portable transfer:** Admin Import/Export writes validated ZIP packages for configuration, configuration with templates, an individual workspace or the full environment. Workspace registries are intentionally local and regenerated on full-environment import.
- **Help:** articles in `help/` are rendered by the in-app document viewer. The Help navigation is an explicit curated list, preventing generic documentation from appearing in the product UI.

Keep generated outputs, database files and customer CDRs out of source-control commits.
