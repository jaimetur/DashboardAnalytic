# Scoring methodology configuration

The workspace database is the authoritative source for scoring rules, weights, thresholds, interpolation anchors, aggregation hierarchy and GAP priorities. The configuration shown in Workspace Config is stored under `scoring_configuration` in the SQLite `workspace_state` table. Calculations use a validated snapshot of that configuration. No JSON reference file is read when opening pages, calculating jobs, displaying results or exporting slides.

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
    "gap_priority": [],
    "aggregation_hierarchy": ["Operator", "Vendor", "Region", "City", "Campaign"]
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
| `aggregation_hierarchy` | All five dimensions exactly once, in display/grouping order. Older imports without this field receive Operator, Vendor, Region, City, Campaign. |
| `gap_priority` | All KPI codes in the chosen comparison priority order. |
| `sources`, source references, `discrepancies` | Optional descriptive provenance; no referenced files are opened. |
| `validation_examples`, `gap_example` | Optional audit/examples, not measurements injected into jobs. |

The formula/filter validator accepts the engine's supported operations rather than executing arbitrary Python or Tableau expressions. Unsupported operations require an implementation change.

## Updating formulas and adding KPIs

KPI formulas and filters live in the workspace configuration under `metrics[].calculation.formula` and `metrics[].calculation.filters`. Workspace Config shows these source definitions for inspection; its editable controls cover thresholds, maximum points, KPI types and score mappings. Formula/filter editing in the panel is currently read-only. The reference `netcheck_2026.json` file is not read during calculation.

To update an existing formula:

1. Back up the workspace and use **Scoring KPI Configuration → Export JSON** to obtain its current settings.
2. Find the KPI by `configuration.metrics[].code`. Edit `calculation.formula`, its `filters` and the descriptive `denominator` as needed. Keep the KPI code, source CDR kind and direction unchanged.
3. Adjust the KPI label, unit and both City/Road `contexts` so the thresholds, maximum points and interpolation anchors match the revised measurement. Preserve its category when reusing an existing KPI. An old threshold is not automatically converted when the formula or unit changes.
4. Increment `configuration.version`, keeping the outer exchange-format `version` at `1`. Retain all 32 metric definitions and their code order, and all codes in `gap_priority`.
5. Import the edited JSON through **Import JSON** or **Admin → Import / Export → Scoring Configuration**. The importer rejects unsupported fields or expressions; it does not execute arbitrary Python or Tableau code.
6. Create or recalculate a job and compare its KPI values and scores with independently verified examples. Completed jobs retain their saved configuration; changing settings does not rewrite their results.

The evaluator supports `AVG(field)`, `MEDIAN(field)`, `PCT90(field)`, the supported conditional percentage ratios and the defined packet-loss ratio. Supported source fields and expression rules are declared in `src/modules/scoring_config.py`; their evaluation is implemented in `src/modules/scoring.py`. Fields and operations outside that catalogue require a code change.

### Replacing or disabling a KPI

A compatible KPI can replace the measurement of an existing code by following the procedure above. For example, C25 can use `AVG(Mean_Data_Rate)` instead of `PCT90(Mean_Data_Rate)` with a mean-throughput label and revised thresholds. It remains a Data KPI where higher is better, retains C25 as its identifier and uses its configured GAP priority. This replaces C25 for future calculations; it does not add a 33rd KPI. Preserve or update its FDTT/DL/Completed filters deliberately.

To stop a KPI contributing points, set its City and Road maximum points to `0` in Workspace Config and save. It remains in the tables and configuration, but contributes no points and does not count toward weighted-score completeness. This does not remove its row or relax the requirement to select Voice, Speech and Data CDRs.

**Current limitation:** the application requires exactly the 32 implemented KPI codes. A definition cannot be deleted, a new code cannot be imported, and an existing code cannot change its source CDR kind or higher/lower-is-better direction through configuration. True additions/removals, unsupported operations or new source fields require development: update the catalogue and validation in `scoring_config.py`, calculation/source-field support in `scoring.py`, and the affected default/fixture configurations and priority lists. Verify calculation, interpolation, completeness, tables/charts, CSV/PPT and configuration import/export/backup round trips before distributing the revised application.

Best Network's Voice/Data family assignment also has a fixed rule: `CLASSIC CALLS`, `WHATSAPP CALLS` and `MULTI RAB` belong to Voice; the remaining categories belong to Data. Renaming these categories or changing that allocation requires updating the corresponding chart rules in `scoring.js` and `scoring_exports.py`, as well as the methodology configuration. A category label is therefore not a substitute for a configurable family-allocation rule.

GAP uses the configured KPI points with the implemented operator-minus-reference comparison. Its subtraction formula is implemented in code and is not a separate editable KPI formula.

## Reference Prep flow and implemented calculation

The supplied Prep flow unions Data, Voice and Speech CSV inputs separately. Its branches filter test/session types and statuses, derive per-row indicators, and aggregate KPI values by `Operator + G_Level_1 + G_Level_2`. It contains 18 aggregation steps followed by 17 inner joins on that dataset key, then writes one KPI CSV. The subsequent Excel workbook performs the KPI-to-score mapping and weighting; Prep itself does not award ranking points.

The application reproduces the supported branch formulas and filters directly on processed CDR rows, pooling rows from selected files before computing ratios, averages, P90 and medians. Before grouping, Operator aliases are normalized using the mapping snapshot saved with the job. It groups only by the selected Operator/Vendor/Region/City/Campaign dimensions, following the saved hierarchy. Campaign grouping is optional: selected campaigns are pooled before KPI calculation when it is unchecked. Historical jobs retain their original grouping semantics. Unlike Prep's inner joins, it preserves groups with missing measurements as N/A and reports incomplete coverage.

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
