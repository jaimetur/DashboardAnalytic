# Web Interface

The web interface provides:

- Login screen
- User workspace for dataset upload and KPI analysis
- Export actions for Word and PowerPoint
- `E2E Bench Dashboard` for the existing interactive KPI analysis
- `E2E Bench Reporting` for template-backed NetCheck CDR reporting
- Administration screen for users, uploaded datasets, and audit logs

The UI is served by FastAPI and uses Jinja templates with a small static CSS and JavaScript layer.

## E2E Bench Reporting

`NetCheck CDR Reports` requires one processed Data CDR, one Voice CDR and one Speech CDR. The user chooses NSA or SA and can generate either a single-vendor or multivendor report. Multivendor reports additionally require a previously processed `Multivendor_Mapping` upload.

`Smart Orchestrator Logs Reports` is intentionally visible but not yet implemented.
