# Scoring methodology configuration

The workspace database is the authoritative source for scoring rules, weights, thresholds, interpolation anchors, aggregation hierarchy and GAP priorities. The configuration shown in Workspace Config is stored under `scoring_configuration` in the SQLite `workspace_state` table. Calculations use a validated snapshot of that configuration. No JSON reference file is read when opening pages, calculating jobs, displaying results or exporting slides.

`assets/scoring/netcheck_2026.json` is a local reference document excluded from Git. It is not distributed with the application or loaded automatically. To initialize an unconfigured workspace, explicitly import a Scoring Configuration JSON or ZIP package. Existing database configurations remain authoritative; invalid data produces an error instead of silently falling back to another methodology.

The original Tableau Prep, Excel, PDF and example PPT are reference material and are not application dependencies. Source names and spreadsheet/Prep references in imported configurations describe provenance only. PowerPoint exports use the application's configured CDR template.

## Named methodologies and portable JSON

Workspace Config stores a collection of named scoring profiles, with one active profile. A profile includes its KPI definitions, per-environment thresholds, maximum points, interpolation mappings, GAP priority and aggregation hierarchy. Existing single-configuration workspaces are treated as a single profile without changing their rules. Selecting a methodology makes it active; Create Profile and Copy Profile select the new copy as active. Edit the active methodology shown in the panel and select the required profile before creating a job; queued and completed jobs keep their captured profile and rule snapshot. The Scoring Calculation methodology dropdown defaults to that active profile but can select another profile for a single job without changing the workspace default. Automatic processing and dataset recalculation continue to use the workspace default. The job captures the chosen profile's rules and aggregation hierarchy.

The JSON exporter and configuration ZIP component carry the complete collection and its active selection:

```json
{
  "format": "dashboard-analytic-scoring-configuration",
  "version": 2,
  "active_profile_id": "netcheck-2026",
  "profiles": [
    {
      "id": "netcheck-2026",
      "name": "Netcheck 2026",
      "configuration": {
        "version": "2026Q2",
        "scope": {},
        "interpolation": {},
        "metrics": [],
        "gap_priority": [],
        "aggregation_hierarchy": ["Operator", "Vendor", "Region", "City", "Campaign"]
      }
    }
  ]
}
```

This abbreviated example illustrates the structure; each nonempty profile needs valid KPI definitions and matching definitions for every configured environment (legacy City/Road files acquire Walk at zero points). Profile `configuration.version` identifies the methodology revision; envelope `version` identifies the exchange format. Legacy version-1 envelopes with a single `configuration` and bare configuration JSON remain importable. Imports, exports, workspace transfers, configuration backups/restores and full workspace backups retain all profiles and the active selection. Importing a collection replaces the destination collection; export it first to keep a copy.

| Configuration field | Meaning |
| --- | --- |
| `scope` | Configured environment keys and their `g_level_1` / optional `g_level_2` CDR matching values. An optional `display_name` records an explicit renamed label; `sheet` remains workbook provenance. Maximum allocations are derived from KPI points. |
| `interpolation` | Default anchors for definitions without explicit per-context mappings. |
| `metrics` | A nonempty collection of uniquely identified KPI definitions, categories, source CDR types, directions, formulas, filters and KPI types. |
| Metric `contexts` | Thresholds, maximum points, relative `weight_share` and normalized score mapping anchors from 0 to 1 for each environment. Relative shares remain meaningful at zero allocated points. |
| `next_kpi_number` | Persisted high-water mark for automatic K-number identifiers; deletions do not recycle earlier codes. |
| `aggregation_hierarchy` | All five dimensions exactly once, in display/grouping order. |
| `gap_priority` | KPI codes in comparison priority order. Removed codes are dropped and new codes are appended. |
| `sources`, source references, `discrepancies` | Optional descriptive provenance; no referenced files are opened. |
| `validation_examples`, `gap_example` | Optional audit examples, never measurements injected into jobs. |

## Editing, replacing, adding and removing KPIs

Formulas and filters are stored inside each profile under `metrics[].calculation`, in the workspace database. Workbook sheet/row provenance such as `source.workbook_sheet` or `source.row` is not used in calculation and is omitted from the table editor. Imported provenance can remain descriptive metadata for exchange compatibility. Formulas and filters are editable in the KPI table; the ignored reference JSON is not a runtime dependency.

1. Export the current collection or back up the workspace before revising a methodology. Select a profile or create a copy with a new name, for example **Netcheck 2025**.
2. Select the environment. KPI rows are grouped by editable category and each category shows its summed maximum points, its weight within the environment and its global weight. Edit labels, category, KPI type, thresholds and score mappings directly.
3. Edit the identifier in the Code column; open the KPI's calculation controls to edit its Data/Voice/Speech source, formula and filter JSON. Calculation basis shows read-only information derived from the formula; it does not control calculation. The formula itself determines the denominator. Imported denominator descriptions are retained as exchange metadata without an editable control. The higher/lower-is-better direction has its own visible selector. KPI codes identify definitions and priority references, rather than formulas. The original NetCheck definitions use K1–K32 in workbook order; legacy C5/C6-style identifiers are converted when loading the editable methodology, without rewriting historical jobs. New KPIs receive the next unused K number. Codes remain stable when moving or deleting rows, so deletions can leave gaps in the sequence. Renaming a code in the table automatically remaps its GAP priority reference on Save, retaining the same position. When hand-editing an exchange JSON, update `gap_priority` references alongside changed codes.
4. Choose **Points** to edit absolute maximum points. Choose **Weight (%)** to edit a KPI's share of the selected environment. KPI weight editing preserves that environment's total and redistributes the other KPI weights proportionally. The separate global percentage is the KPI points divided by the total points of all environments. The environment allocation editor changes its total points; editing its global percentage preserves the grand total and redistributes the other environments proportionally. Relative weights remain editable even at zero environment points, ready for a later allocation. Use Distribute Points to open a dialog, choose a reference environment and enter the selected environment's total points. The selected environment receives that total multiplied by each reference KPI's relative share, including saved relative shares in a zero-point environment. Thresholds and formulas are unchanged. Review the draft distribution and save the KPI configuration. Category totals refresh with the edits.
5. Use Add KPI or the Add action on a KPI row to insert a supported definition; the row action inserts directly below that row in the same category. Move Up/Down changes the order within its category. Alternatively, replace an existing definition's label, category, source, direction, formula, filters, thresholds and points. Each environment definition must remain valid. Delete a KPI to remove its row and contribution from future calculations; at least one KPI must remain. Set maximum points to zero instead to keep a non-contributing KPI visible.
6. Set the GAP priority, whose table also shows each KPI's category, and save the profile. Replacing or deleting an identifier updates priority membership. Activate the profile intended for future jobs.
7. Create or recalculate a job and compare its KPI values and interpolated scores against independently verified examples. Changes never rewrite earlier job snapshots.

For example, add a definition below the FDTT DL throughput P90 KPI (K20 in the original 2026 ordering), use `AVG(Mean_Data_Rate)` in place of `PCT90(Mean_Data_Rate)`, rename it to mean throughput and revise its thresholds. Deliberately preserve or change its FDTT/DL/Completed filters. Delete the original P90 definition if this is a replacement rather than an extra contribution, then save and activate the revised profile.

The imported KPI Type labels classify reliability/minimum-service indicators as **Reliable** and performance differentiators as **Diff**. Type is descriptive metadata used in tables and exports; it does not change interpolation or GAP arithmetic. Formula, source filters, direction, thresholds and maximum points determine the calculation.

### Supported expression language and limits

The evaluator supports `AVG(field)`, `MEDIAN(field)`, `PCT90(field)`, `SUM(field)`, `COUNT(field)`, supported conditional ratios with an optional factor of 100, and the defined packet-loss ratio. Examples include `AVG(Call_Setup_Time)` and `100 * SUM(Call_Status == "Completed") / COUNT(Call_Status)`. Conditions support the implemented comparisons, `AND`, `CONTAINS(...)` and `IS NOT NULL`. Filters are JSON objects: for example `{"Session_Type": ["CALL", "MultiRAB CALL"], "Call_Status": ["Completed", "Dropped"]}`. The packet-loss expression is shown only for the Interactivity packet-error formula. It adds lost, discarded, corrupted and unsent packets, treating null values and omitted optional loss-component columns as zero for this explicit IFNULL formula. `Packets_Sent` remains required, and its summed denominator must be positive; missing or zero sent packets produce N/A. This does not make absent input fields optional for other formulas; the supported expression is `IFNULL(Packets_Lost,0) + IFNULL(Packets_Discarded,0) + IFNULL(INT(Packets_Corrupted),0) + IFNULL(Packets_Not_Sent,0)`. Its editor shows the supported expression as read-only reference with help; changing to the packet-loss formula supplies it automatically. It is not needed for other KPIs. Source fields and exact accepted grammar are declared in `src/modules/scoring_config.py`; their evaluation is implemented in `src/modules/scoring.py`.

Imported custom KPI identifiers remain supported, with up to 256 KPIs and 32 environments per profile, and up to 64 profiles per workspace. Code is edited only in its column immediately before KPI; its generated sequence is preserved across reordering and deletion. Arbitrary Python, SQL or Tableau expressions are not executed. Create Environment opens a dialog for its name, reference environment, total points, `G_Level_1` and optional `G_Level_2`. Every KPI receives a context copied from the reference, with points allocated using its relative shares; the new source-matching values determine the rows used. Environment matching fields remain editable. Names are unique (case-insensitively), and Combined is reserved for the computed total. Source selections cannot overlap: two definitions with the same `G_Level_1` cannot use the same `G_Level_2`, or leave it unrestricted while another selects a subset. Rename Environment changes the name and every KPI context key together, preserving points, relative shares, thresholds and source selectors. Renamed environments remain renamed through JSON/ZIP import/export, transfers and backup/restore. Save the profile before calculating new jobs; historical job snapshots retain their original names. Delete Environment removes that context from every KPI in the draft. Keep at least one environment and a positive overall allocation, then save. Saved jobs retain their original environment definitions. New operations or source fields outside the expression allowlist still require a code change and regression tests. The application continues to require complete Data, Voice and Speech CDR selections for scoring.

Best Network assigns Voice/Speech KPIs to Voice and Data KPIs to Data using each KPI's source type, so category names can be changed without changing that allocation. GAP remains the implemented subtraction **operator points − reference points**. Category and final GAP rows show arithmetic means of valid KPI comparisons, excluding N/A; the final mean always uses the original KPI rows, not an unweighted average of category means. These display aggregates do not alter the underlying KPI measurements or weighted-score totals.

## NetCheck 2026 workbook verification

The initial 2026 profile was checked directly against `Netcheck_Score_Mapping_2026Q2_BestNetwork_Drive_City_Road.xlsx`: 32 KPI definitions in each of the workbook sheets DriveCity and DriveConnectionroad, rows 4–35. The current Road environment is named **Drive Connecting Roads** and matches `G_Level_1 = Drive`, `G_Level_2 = Connecting Roads`; the workbook sheet name remains descriptive provenance. Every maximum allocation in column F matches within 1e-12; the environment totals are 650 and 350 points. Thresholds in G:J, numeric Ultra values and best-value Ultra formulas match the source mapping. Walk is a zero-point extension, with City-derived starting rules. Category spelling/capitalization is normalized for display; it does not change weights or formulas. The application and regression tests do not open that workbook at runtime. Workspace profile reads correct the known NetCheck 2026 legacy Road name/selector while preserving its allocations; explicit environment renames and customized source selectors are retained. This correction does not rewrite historical job configurations.

## Reference Prep flow and implemented calculation

The supplied Prep flow unions Data, Voice and Speech CSV inputs separately. Its branches filter test/session types and statuses, derive per-row indicators, and aggregate KPI values by `Operator + G_Level_1 + G_Level_2`. It contains 18 aggregation steps followed by 17 inner joins on that dataset key, then writes one KPI CSV. The subsequent Excel workbook performs the KPI-to-score mapping and weighting; Prep itself does not award ranking points.

The application reproduces the supported branch formulas and filters directly on processed CDR rows, pooling rows from selected files before computing ratios, averages, P90 and medians. Before grouping, Operator aliases are normalized using the mapping snapshot saved with the job. It groups only by the selected Operator/Vendor/Region/City/Campaign dimensions, following the saved hierarchy. Campaign grouping is optional: selected campaigns are pooled before KPI calculation when it is unchecked. Historical jobs retain their original grouping semantics. Unlike Prep's inner joins, it preserves groups with missing measurements as N/A and reports incomplete coverage.

For each KPI/context, the engine interpolates its measured value between Low, Medium, High and optional Ultra. Default anchors are 0%, 80%, 100% without Ultra; with Ultra, K20/K25 (legacy C25/C30) use High = 90% and other supported mappings use 95%, with Ultra = 100%. Normalized scores are multiplied by configured maximum points, then summed by category/environment. The NetCheck 2026 allocation starts at 650 City, 350 Road and 0 Walk points. Walk matches `G_Level_1 = Walk` regardless of `G_Level_2`; its initial thresholds match City and must be validated before assigning it points. All Environments (Combined) uses the sum of each KPI’s configured maximum points across every environment, independently of source coverage. Positive-weight environments are required for complete measured scores; missing environments keep their configured maximum allocation and flag available scores as incomplete. A zero-weight Walk contributes zero and does not make City/Road scores incomplete. Tables, category/overall chart allocations and PowerPoint share these maxima. GAP is operator points minus reference points within the same aggregation context. All Environments compares only complete contributions from environments common to both sides, marks partial comparisons with an asterisk, and reports N/A when no common contribution or reference exists. Saved jobs contain the input/configuration identity, raw measurements, scores, totals and warnings; exports read those saved results.

Regression tests cover representative raw-input calculations and extracted workbook mapping examples, including the P90 High/Ultra interpolation segment. They do not establish full numerical parity with a complete real-world Prep output: that requires matching CDR inputs, campaign grouping, environment coverage, operator scope and a verified reference output.

## Import, edit and update a methodology

Import and export through **Workspace Config → Scoring KPI Configuration** or **Admin → Import / Export → Scoring Configuration**. Use a copied, inactive profile to prepare a revised methodology, update supported formulas and weights, verify it, then activate it. The same component transfers the profile collection, hierarchy and GAP priorities and restores them from configuration backups. An unconfigured workspace remains explicitly unconfigured instead of acquiring hidden defaults.

For a future NetCheck revision, compare its formulas, filters and mapping anchors with verified examples, update the profile's methodology version in its exported/imported JSON if needed, and validate a new job. New KPI additions and removals are supported in the panel; unsupported fields, operations or environments require engine support first. Legacy reference files can be imported explicitly, and completed jobs retain their original settings.

Regression tests use independent Python fixtures and do not depend on the ignored local JSON or original reference documents. A full benchmark parity check requires matching raw CDR inputs and a verified Prep/Excel output.

See [Scoring & GAP Analysis](scoring-gap-analysis.md) for coverage, tables/charts and exports.
