# Bench Automations

Bench Automations is a multi-user web platform for processing CSV/XLSX datasets from NetCheck and Smart Orchestrator, computing KPIs, visualizing CDF curves, and exporting reports to Word and PowerPoint.

## MVP Scope

- FastAPI backend with role-based authentication (`admin`, `user`)
- User panel for dataset upload, filtering, KPI analysis, and report export
- Administration panel for users, datasets, and audit logs
- CSV and Excel ingestion
- KPI cards, percentile scorecard, and CDF visualization
- Docker and `docker-compose` deployment with `.env` configuration
- GitHub Actions for tests, Docker builds, and source packaging

## Structure

- `src/`: application code, modules, utilities, and web interface
- `tests/`: unit and light integration tests
- `docker/`: local and development deployment files
- `data/`: input, output, and exported artifacts
- `config/`: persisted SQLite database and runtime configuration
- `help/`: project documentation

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn src.BenchAutomations:app --reload --port 7279
```

## Docker Run

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

## Default Credentials

- `admin / admin123`
- `demo / demo123`

## Current State

The current base already supports dataset upload, KPI analysis, basic visualization, report export, and administration. NetCheck-specific scoring rules, region or cluster GAP logic, and final branded Word or PowerPoint templates can be added in a next iteration once the real input formats are available.
