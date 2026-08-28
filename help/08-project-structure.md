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
├── assets/slides-templates/       # NSA/SA Slides Templates CSVs and workspace library
├── help/                          # Help-centre Markdown articles
├── tests/                         # automated tests
├── docker/                        # Compose definitions and environment configuration
├── data/                          # runtime data when configured locally
└── README.md                      # project overview and quick start
```

## Key implementation areas

- **Routes and pages:** `src/DashboardAnalytic.py` exposes API and document/help routes; `src/web_interface/templates/` contains the application, reporting and Help views.
- **Reporting:** the reporting module loads processed CDR data, applies NSA/SA and persisted vendor logic, parses filters and row/column grouping from the selected Slides Templates, then fills the supplied PowerPoint layouts. The PowerPoint master is kept in `assets/ppt-templates/` so deployments do not depend on a user desktop.
- **Slides Templates assets:** `assets/slides-templates/library/nsa/` and `library/sa/` are the complete canonical library, including each technology's default template. `assets/slides-templates/default/nsa/` and `default/sa/` contain only a same-named active mirror for report generation. The Admin editor and importer use this schema as the executable chart contract.
- **Persistence:** the data modules keep workspace metadata and processed datasets available for later Dashboard and Reporting use.
- **Help:** articles in `help/` are rendered by the in-app document viewer. The Help navigation is an explicit curated list, preventing generic documentation from appearing in the product UI.

Keep generated outputs, database files and customer CDRs out of source-control commits.
