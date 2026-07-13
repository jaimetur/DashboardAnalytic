# 🗓️ CHANGELOG
[Planned Roadmap](/ROADMAP.md) for the following releases
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.1.0
### Release Date: 2026-07-13

#### 🌟 New Features:
- Initial Dashboard Analytic MVP for KPI analytics
- FastAPI multi-user web interface
- CSV/XLSX ingestion, KPI scoring, CDF chart, and report exports
- Docker and GitHub Actions setup
- Added automatic CDR workbook processing for `.xlsm`, including multi-sheet operator imports
- Added cached dataset profiles with status, progress, retry, and deduplication by source file
- Redesigned the dashboard with a queue table, right-side filters, and collapsible panels
- Moved workspace loading to cached metadata and delayed full analysis until requested
- Refreshed the login screen and added asset versioning for CSS and JS reloads
- Added a global processing overlay for uploads, retries, dashboard updates, and exports
- Renamed the main FastAPI entrypoint to `DashboardAnalytic.py`
- Added `Readme` and `Changelog` navigation with Markdown document viewer
- Cached dashboard analyses to avoid reloading the dataset on repeated page refreshes
- Renamed the ingestion panels to `Data Ingestion` and `Data Processing Queue`
- Fixed document links to open `Readme` and `Changelog` in a new tab
- Updated production Docker compose to pull published Docker Hub images
