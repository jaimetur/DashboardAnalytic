# Scoring methodology configuration

The workspace database is the authoritative source for scoring rules, weights, thresholds, interpolation anchors and GAP priorities. The configuration shown in Workspace Config is stored under `scoring_configuration` in the SQLite `workspace_state` table. Calculations use a validated snapshot of that configuration. No JSON reference file is read when opening pages, calculating jobs, displaying results or exporting slides.

`assets/scoring/netcheck_2026.json` is a local reference document excluded from Git. It is not distributed with the application or loaded automatically. To initialize an unconfigured workspace, explicitly import a Scoring Configuration JSON or ZIP package. Existing database configurations remain authoritative; invalid data produces an error instead of silently falling back to another methodology.

The original Tableau Prep, Excel, PDF and example PPT are reference material and are not application dependencies. Source names and spreadsheet/Prep references in imported configurations describe provenance only. PowerPoint exports use the application's configured CDR template.

## Portable JSON format

The direct JSON importer and exporter use the same envelope as the configuration document inside ZIP packages:

```json
{
  "format": "dashboard-analytic-scoring-configuration",
  "version": 1,
  "configuration": {
    "version": "2026Q2",
    "scope": {},
    "interpolation": {},
    "metrics": [],
    "gap_priority": []
  }
}
```

This abbreviated example shows the structure; imports require all supported KPI definitions and environments. `configuration.version` identifies the methodology; envelope `version` identifies the exchange format.

| Configuration field | Meaning |
| --- | --- |
| `scope` | Supported City/Road environment labels and source grouping fields. Maximum allocations are derived from KPI weights. |
| `interpolation` | Default anchors used to normalize imported definitions that omit explicit per-context mappings. |
| `metrics` | The 32 supported KPI definitions, source CDR types, directions, formulas, filters, KPI types and City/Road contexts. |
| Metric `contexts` | Thresholds, maximum points and normalized `score_mapping` anchors from 0 to 1. |
| `gap_priority` | All KPI codes in the chosen comparison priority order. |
| `sources`, source references, `discrepancies` | Optional descriptive provenance; no referenced files are opened. |
| `validation_examples`, `gap_example` | Optional audit/examples, not measurements injected into jobs. |

The formula/filter validator accepts the engine's supported operations rather than executing arbitrary Python or Tableau expressions. Unsupported operations require an implementation change.

## Reference Prep flow and implemented calculation

The supplied Prep flow unions Data, Voice and Speech CSV inputs separately. Its branches filter test/session types and statuses, derive per-row indicators, and aggregate KPI values by `Operator + G_Level_1 + G_Level_2`. It contains 18 aggregation steps followed by 17 inner joins on that dataset key, then writes one KPI CSV. The subsequent Excel workbook performs the KPI-to-score mapping and weighting; Prep itself does not award ranking points.

The application reproduces the supported branch formulas and filters directly on processed CDR rows, pooling rows from selected files before computing ratios, averages, P90 and medians. It additionally groups by Campaign and the selected geography/vendor dimensions. Unlike Prep's inner joins, it preserves groups with missing measurements as N/A and reports incomplete coverage.

For each KPI/context, the engine interpolates its measured value between Low, Medium, High and optional Ultra. Default anchors are 0%, 80%, 100% without Ultra; with Ultra, C25/C30 use High = 90% and other supported mappings use 95%, with Ultra = 100%. Normalized scores are multiplied by configured maximum points, then summed by category/environment. The default allocation is 650 City and 350 Road points. GAP is operator points minus reference points. Saved jobs contain the input/configuration identity, raw measurements, scores, totals and warnings; exports read those saved results.

Regression tests cover representative raw-input calculations and extracted workbook mapping examples, including the P90 High/Ultra interpolation segment. They do not establish full numerical parity with a complete real-world Prep output: that requires matching CDR inputs, campaign grouping, environment coverage, operator scope and a verified reference output.

## Import, edit and update a methodology

1. Open **Workspace Config → Scoring KPI Configuration → Import JSON**, or select the JSON/ZIP through **Admin → Import / Export** and choose destination workspaces. The local NetCheck reference uses this same importable format.
2. Change City/Road maximum points, KPI type, thresholds and score anchors in the table. UI anchors use percentages; stored mappings use fractions from 0 to 1. Save the panel.
3. Set and save the order in **GAP KPI Priority**, below the KPI panel.
4. Calculate a new job. Configuration changes generate a different cache identity. Completed jobs retain their saved measurements and configuration snapshot; they are not recalculated when settings change.
5. Use **Export JSON** or the **Scoring Configuration** export component to transfer both panels together. Configuration backups/restores and full workspace database backups preserve them too. An unconfigured workspace is represented explicitly as `configuration: null` inside backup packages; it does not acquire hidden defaults.

For a future NetCheck revision, export and back up the current settings, compare the revised formulas/filters, weights and per-KPI anchors against verified examples, and import the updated methodology explicitly. Increment `configuration.version`, retaining the exchange-format version. Numerical settings and supported formulas can be supplied through the configuration; new KPI codes, source columns, operations or environments require engine/schema/UI support and regression tests first. Importing a document never changes historical job snapshots.

Regression tests use independent Python fixtures and do not depend on the ignored local JSON or original reference documents. A full benchmark parity check requires matching raw CDR inputs and a verified Prep/Excel output.

See [Scoring & GAP Analysis](scoring-gap-analysis.md) for coverage, tables/charts and exports.
