# Product roadmap

## Current scope

Dashboard Analytic currently provides isolated named Workspaces, the E2E Dashboard for interactive KPI inspection and E2E PowerPoint Reporting for NetCheck CDR PowerPoint generation. Administrators can also manage templates and inspect/edit the active workspace database.

NetCheck reporting supports Data, Voice and Speech CDR inputs, NSA/SA selection, single-vendor reports and multivendor reports from Vendor values mapped in Workspace using VFUK/3UK datasets. The output uses selected named Slides Templates and the project PowerPoint template, while leaving analyst comment areas available for manual conclusions.

## Planned reporting work

- **Smart Orchestrator Logs Reports:** its selectable entry is already visible in Reporting, but its input model, KPI mapping and report generator are not implemented.
- **Scoring and GAP analysis:** the corresponding template slides are retained, but their business calculations and automatic population remain future work.
- **Expanded KPI contracts:** continue validating each NSA/SA chart against approved NetCheck CDR definitions, template geometry, thresholds and scoring definitions.

## Documentation work

Future documentation can add anonymised CDR schema examples, mapping-file examples and a slide-by-slide reporting contract. These additions should be based on approved representative data and must not include customer identifiers.
