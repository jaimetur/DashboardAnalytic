# 🗓️ CHANGELOG
[Planned Roadmap](/ROADMAP.md) for the following releases
[Changelog](/CHANGELOG.md) for the past releases

---

## Release: v0.1.0
### Release Date: 2026-07-14

#### 🌟 New Features:
- Initial Dashboard Analytic MVP for KPI analytics
- FastAPI multi-user web interface
- CSV/XLSX ingestion, KPI scoring, CDF chart, and report exports
- Docker and GitHub Actions setup
- Added automatic CDR workbook processing for `.xlsm`, including multi-sheet operator imports
- Added cached dataset profiles with status, progress, retry, and deduplication by source file
- Added a global processing overlay for uploads, retries, dashboard updates, and exports
- Added app branding assets, favicon support, and header user badges by role
- Expanded the admin `Identity` panel with inline edit, toggle active, and delete actions

#### 🚀 Enhancements:
- Redesigned the dashboard with a queue table, right-side filters, and collapsible panels
- Moved workspace loading to cached metadata and delayed full analysis until requested
- Refreshed the login screen and added asset versioning for CSS and JS reloads
- Cached dashboard analyses to avoid reloading the dataset on repeated page refreshes
- Renamed the ingestion panels to `Data Ingestion` and `Data Processing Queue`
- Updated production Docker compose to pull published Docker Hub images
- Added login hero logo placement and refined login spacing
- Replaced the browser delete confirm with a styled confirmation modal
- Added multi-file upload with chunked file writes for large datasets
- Updated the queue to refresh progress live without page reloads
- Switched the upload file picker copy to English labels
- Added finer-grained dataset processing progress updates for large files
- Refined the workspace selector layout and queue action button styling
- Renamed the dataset summary panel to `Selected Dataset`

#### 🐛 Bug fixes:
- Fixed default access visibility to reflect active users with default passwords only
- Prevented removing, deactivating, or demoting the last active admin user
- Fixed embedded document images to resolve project `static` asset paths
- Fixed empty-state body copy alignment in the workspace panels
- Fixed dataset selector filtering so all datasets show when no type filter is set
- Improved dataset kind detection for `CDR-Speech` and `CDR-Data`
- Fixed the dataset picker to react immediately when `Input Type` changes
- Fixed the upload file input overlay so `Upload and process` submits directly

#### 📚 Documentation:
- Added `Readme` and `Changelog` navigation with Markdown document viewer
- Added the app logo at the top of the `README`
- Fixed document links to open `Readme` and `Changelog` in a new tab
