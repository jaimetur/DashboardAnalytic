# Scoring & GAP Analysis

Calculate KPI scores from processed Data, Voice and Speech CDRs, then compare each operator with a reference operator. Results belong to the workspace and do not require a Dashboard or Report Template.

> [!NOTE]
> **Start with a saved methodology.** It defines the environments, KPI formulas, thresholds and maximum points. The selected job keeps a snapshot of these rules.

## Choose your task

| I want to… | Go to |
| --- | --- |
| Calculate or recalculate a comparison | [Calculate and review](#calculate-and-review) |
| Understand filters and aggregation | [Filters and aggregation](#filters-and-aggregation) |
| Read scores, GAPs and coverage warnings | [Results and workspace settings](#results-and-workspace-settings) |
| Change environments, KPIs or weights | [Methodology](#methodology) |
| Edit formulas and scoring rules | [KPI definitions](#editing-replacing-adding-and-removing-kpis) |
| Understand methodology JSON | [Portable JSON reference](#portable-json-reference) |
| Inspect original KPI weights and sources | [Supported KPI allocation](#supported-kpi-allocation) |
| Share results or preserve a workspace | [Persistence and exports](#persistence-and-exports) |
| Resolve missing results | [Troubleshooting](#troubleshooting) |

## Calculate and review

### 1. Prepare the inputs

1. Open the correct workspace and finish processing the required CDRs.
2. If no methodology is configured, import one under **Workspace Config → Scoring & GAP Analysis Setup**.
3. Open **Scoring & GAP Analysis** and expand **Select CDRs, filters, aggregation levels & GAP reference**.
4. Choose **NSA** or **SA** above **CDR datasets**. A job cannot mix both modes.

> [!IMPORTANT]
> Include at least one ready **Data**, **Voice** and **Speech** CDR for every campaign included in the calculation. Complete CDR selection does not guarantee complete KPI measurements: inspect Calculation notes after processing.

### 2. Select CDRs

Use the Data, Voice and Speech selectors, or replace the selection with a shortcut:

| Button | Selection |
| --- | --- |
| **Select all CDRs** | All ready CDRs in the selected NR Mode |
| **Select latest of each type** | The latest ready Data, Voice and Speech CDR |
| **Select latest two of each type** | Up to two latest ready CDRs per type |

“Latest” first uses a recognized date in the CDR name: year-quarter, YYYY-MM-DD, DD-MM-YYYY or a compact date. When no name date is recognized, upload time is used. Ties use upload time, then dataset ID.

On first use, the module selects the latest ready CDR of each type for the chosen NR Mode.

### 3. Set filters, aggregation and reference

1. Restrict **Operators**, **Vendors**, **Regions**, **Cities** or **Campaigns** if needed.
2. Choose the aggregation levels (Operator, Vendor, Region, **Cluster**, City and Campaign, in the order of the methodology). **Operator** is always included; additional levels split the results into separate combinations. Cluster needs CDRs with a `Cluster` column, filled by the source CDR or by a Cluster mapping.
3. In **GAP reference operator**, select the operator to compare against. The initial reference is **EE**.
4. Choose the saved **Scoring Methodology** beside Calculate and Recalculate.

The configured hierarchy determines the order of the filter controls and aggregation headers. The initial order is **Operator → Vendor → Region → City → Campaign**.

### 4. Calculate or recalculate

| Situation | Action |
| --- | --- |
| No matching job exists | **Calculate Scoring** creates a job |
| A matching job already exists | **Calculate Scoring** is disabled; **Recalculate** updates that job |
| An identical job is queued or running | Both actions are disabled until it finishes |

Matching checks the CDR content, NR Mode, filters, aggregation levels, GAP reference and saved methodology. A change to these inputs can produce a different job, even when its visible title looks similar.

Recalculation keeps the job identifier, replaces its results and updates the displayed date/time to the recalculation submission time. Job lists show the latest calculations first.

> [!TIP]
> Read the **yellow message below the methodology selector** when an action is unavailable. It explains duplicate jobs, incomplete selections and other calculation conditions.

### 5. Open a saved job

Select a job in the **Scoring Results** dropdown or the **Scoring Jobs** history. The module loads its saved results and restores its calculation inputs so you can relaunch it.

Job cards show filters, ordered aggregation levels, **GAP Reference** and **Scoring Methodology**. The job name lists the date, NR Mode, Regions, **Clusters** (in their own colour), Cities, Operators, Vendors and Campaigns, and the generated PowerPoint is named `yyyymmdd_hhmmss - Scoring & GAP Analysis - <NR Mode> - <Regions> - <Clusters> - <Cities> - <Operators> - <Vendors> - <Campaigns>.pptx`. A complete vendor selection appears as **All Vendors**. Hover or click the **CDRs** button to inspect the source files.

Deleting a job removes its saved results after confirmation; it does not delete its source CDRs. Running work stops at a processing checkpoint or discards its pending result.

### What is remembered?

- **Shared across workspace users and browsers:** CDRs, NR Mode, methodology, filters, aggregation and GAP reference. These calculation selections save automatically.
- **Within the browser session:** result tab, environment, display controls, comparison selection and scroll position.
- **Inside each job:** source metadata, rules, grouping, results and warnings captured for that calculation.

Automatic job refreshes do not overwrite edits to the calculation controls. Removed or unready inputs produce a notice when a saved selection is restored.

## Filters and aggregation

### Filtering chooses rows; aggregation chooses groups

| Control | Example | Effect |
| --- | --- | --- |
| Filter | City = Leeds and London | Include rows from either city |
| Aggregation | Operator → City → Campaign | Calculate separate results for each operator/city/campaign combination |
| Omit an aggregation level | Campaign not selected | Pool the selected campaigns' raw rows before calculating KPIs |

Values within a filter combine with **OR**. Different filter fields combine with **AND**. An empty selection means all values. **Main Cities** selects configured workspace cities that exist in the selected CDRs.

The engine pools raw rows before calculating ratios, averages, medians and P90. It does not average KPI results already calculated from separate files.

> [!TIP]
> Select **Campaign** when you want a separate column or bar for each campaign. Filtering two campaigns alone does not separate their results.

### Vendor filtering

The **Operator_Vendor** selector filters the `<Operator>_<Vendor>` identity and the **Vendor** selector the vendor alone, using cached per-CDR values; **Cluster** follows Region and **City** offers **Main Cities** first. Choices appear in this order: real vendors, Ericsson_Mixed (and the former Mixed Vendor), Non-Ericsson_Mixed (and the former Other Vendor), All Vendor(s), then operators without assigned vendors labelled **Operator - All**.

Selecting **Ericsson** and **Huawei** includes only those vendor identities from the selected operators. To include an operator with no assigned vendor, also select its **Operator - All** choice, or leave the Vendor filter unrestricted. Vendor mapping stores the suffix in `Operator_Vendor` and `Vendor`; legacy operator-only values without it remain supported.

Legacy saved operator-prefixed selections are normalized to vendor names. The **Operator** filter remains independent. When Vendor is an aggregation level, operators without a vendor still display **All** in that level; web and PowerPoint retain the existing comparison and reference behavior.

### How the GAP reference is matched

Each comparison retains the selected environment and aggregation context. For vendor comparisons, the engine tries the same vendor first, then the reference operator's **All** vendor group.

> [!NOTE]
> **EE / All can be the reference for Ericsson, Huawei and other vendor groups.** Campaign, City, Region and other selected levels must still match. The fallback does not compare different cities or campaigns.

No matching reference or no common valid environment contribution produces **N/A***.

Filter choices use cached CDR catalogues. If an older CDR lacks expected choices, reprocess it to refresh its catalogue.

## Results and workspace settings

### Choose an environment

The **Environment** selector applies to all result tabs and exports. An individual environment shows its own contribution; **All Environments** combines the configured environments.

For the initial NetCheck 2026 allocation:

| Environment | Configured maximum |
| --- | ---: |
| Drive - City | 650 points |
| Drive - Connecting Roads | 350 points |
| Walk | 0 initial points |
| All Environments | 1,000 points |

Custom methodologies can change these allocations. When the combined result has incomplete coverage, opening a job prefers an available environment with complete coverage. You can still select All Environments.

### Scoring Tables

| View | What it shows |
| --- | --- |
| **Summary** | Category totals and the weighted score total |
| **Breakdown** | Each KPI, its maximum points and weight, plus category subtotals |
| **Show KPI values** | Measured KPI values in Breakdown, before the Score columns |
| **Show GAP values** | GAP columns at the end or next to each compared operator's score |

Summary highlights the highest and lowest valid scores **across the whole displayed row**. Tied extremes can highlight several cells. Equal scores, or fewer than two valid scores, remain neutral.

Breakdown score colors use **Low**, **Medium**, **High** and **UltraHigh** bands. Category totals remain neutral. Raw measurements are not summed across different KPIs because their units differ.

GAP visibility starts unchecked. It affects Scoring Tables and its PowerPoint tables; dedicated GAP Analysis views remain available.

### GAP Analysis

**GAP = compared operator weighted points − reference operator weighted points.**

| Value | Meaning |
| --- | --- |
| Positive / green | The compared operator leads the reference |
| Negative / red | The compared operator trails the reference |
| Zero | Equal weighted points |
| **N/A*** | No valid comparison is available |

**GAP comparison** offers **All vs reference** and each individual operator. Individual comparisons order KPI rows from lowest to highest GAP, with unavailable values last. All Operators retains KPI definition order. Saved GAP priorities do not control this display order.

Every GAP table ends with **Total KPI GAP**, the sum of the valid KPI GAPs in **each column separately**, in web and PowerPoint.

Individual PowerPoint slides also show:

| Side note | Calculation |
| --- | --- |
| **Average KPI GAP** | Mean of all valid KPI GAP cells displayed on the slide |
| **Average total KPI GAP** | Calculate each column's KPI sum, then average those column totals |

Columns represent combinations of the selected levels, such as City and Campaign. Columns without any valid GAPs are excluded from the mean of totals.

> [!IMPORTANT]
> **Do not apply KPI weights again to GAP points.** Each KPI GAP already subtracts weighted scoring points. Totals sum those points; averages use them directly.

**Example — two campaign columns:** Q1 totals −51.64 points and Q2 totals −87.08 points. The **Average total KPI GAP** is `(−51.64 − 87.08) / 2 = −69.36 points`. This differs from the mean per KPI.

### Scoring Charts

| Chart | Use it to… |
| --- | --- |
| **Best Network Scoring per Service** | Compare total points and Data/Voice contributions; Data stacks below Voice |
| **Best Network Scoring per Category** | Compare category contributions within each operator/context stack |
| **Scoring per Category** | Compare operators directly within each category |
| **Maximum score allocation donuts** | Inspect configured environment, service and category maxima and shares |

Voice and Speech KPIs contribute to **Voice**; Data KPIs contribute to **Data**, regardless of category names. Allocation donuts show **maximum available allocation**, not earned scores.

Hover bars, segments, totals or donut sectors for values and context. Double-click charts for an enlarged view. Dense web charts scroll horizontally. Operator Mapping supplies labels, order and colors.

A single aggregation level uses normal axis labels; multiple levels use separate header rows. Campaign labels display year-quarter, such as **2026-Q1**, while stored campaign names and CSV identifiers remain unchanged.

### Incomplete coverage and achievable scoring

The pale yellow **Calculation notes** card lists affected combinations, missing KPI names and the **exact maximum achievable score** after excluding their unavailable contributions.

> [!WARNING]
> **Missing points are not redistributed.** An incomplete result keeps the original weights and configured benchmark maximum. Available contributions are not scaled up to a complete score.

Example: **VF_UK / Samsung / Q1: maximum 583.2645 of 650 points**, with the unavailable KPI names listed below. Another campaign can have a different achievable maximum because different KPIs are missing.

- Incomplete numeric values appear **in bold red with `*`**.
- Unavailable values appear **as N/A*** in the same style.
- Total KPI GAP sums available contributions and carries `*` when a contribution is missing or partial.
- All Environments GAP uses valid environment contributions common to both sides. A subset is partial; no common contribution is unavailable.
- Tooltips explain partial GAP coverage; PowerPoint slide notes include the coverage details.

All Environments raw KPI values are calculated from pooled source rows, not averaged from environment KPI values. Older jobs without these saved measurements show N/A until recalculated. Weighted scoring points still sum the separately calculated environment contributions.

## Methodology

A methodology contains the complete environment, KPI, weighting, threshold, hierarchy and priority setup. Open **Workspace Config → Scoring & GAP Analysis Setup** to edit it. Calculation and Results shortcuts open the relevant sections directly.

### Named methodologies and portable JSON

Open **Workspace Config → Scoring & GAP Analysis Setup**. Select a methodology or use **Create Methodology** / **Duplicate Methodology** to prepare another one.

The selector's name identifies the methodology. **Methodology title** is an optional editable description preserved in transfers.

#### One complete save

The toolbar and three sibling panels offer the same **Save Methodology** action:

| Panel | Settings included in the save |
| --- | --- |
| **Methodology Environments** | All environments, allocations, KPI specifications and thresholds |
| **Methodology Aggregation Hierarchy** | Ordered grouping dimensions |
| **Methodology KPIs Priorities for GAP analysis** | Saved priority order |

> [!NOTE]
> **Save Methodology commits all pending settings together.** The buttons are convenient entry points to one complete save, not separate panel-specific saves. The shared status above the panels indicates saved or pending changes.

Selecting a methodology does not change the workspace default. **Set Default** chooses the methodology used by future default/automatic calculations. You can choose another saved methodology for a manual job.

The default methodology cannot be deleted until another is set as default. Completed jobs keep their captured rules and results after editing or deleting a methodology.

#### Save versus export

| Action | Scope | Result |
| --- | --- | --- |
| **Save Methodology** | Open methodology and all pending edits | Writes to the workspace database |
| **Export Methodology (JSON)** | Selected saved methodology | Downloads a one-methodology document |
| **Import Methodology (JSON)** | One methodology or a collection | Adds IDs and replaces matching IDs after confirmation, preserving other methodologies and the existing default |
| **Admin Scoring Configuration export/import** | Complete collection and default | Transfers the workspace's methodology setup |
| **Configuration backup / restore** | Included scoring configuration component | Preserves/restores the collection and default |
| **Workspace database backup / restore** | Whole workspace database | Also preserves jobs, results and local calculation selections |

> [!TIP]
> Save pending edits before exporting. Duplicate a methodology before revising a benchmark, and export or back up the collection before replacing it through Admin.

The editor import merges by methodology ID. Duplicate names with different IDs are rejected. Collection replacement through Admin replaces the destination collection; review its contents first.

### Configure environments

An environment defines **which CDR rows to include** and **how many points its KPIs can contribute**. It belongs to the selected methodology.

#### Source-row matching

Select the environment and use **CDR filters**:

| Field | Meaning | Example |
| --- | --- | --- |
| **G_Level_1** | Required first-level source value | Drive |
| **G_Level_2** | Optional second-level source value | City |

With Drive and City selected, only rows matching **both** values are included. Leaving G_Level_2 empty includes every second-level value for the selected G_Level_1.

These source values are different from geographic Region/City filters. Changing an environment's display name does not change its matching rule.

> [!WARNING]
> **Environment source rules cannot overlap.** Two environments cannot select the same first/second-level combination. An unrestricted second level also conflicts with a narrower environment using the same first level.

Available choices come from ready workspace CDR catalogues. Saved source values remain selectable even when absent from current CDRs. Configuration exports carry the selected values; available choices at the destination come from its own CDRs.

#### Create, rename or delete

1. Use **Create Environment** and enter its name, reference environment, points and source filters.
2. The new environment copies KPI thresholds and relative shares from the reference.
3. Review the copied rules, then **Save Methodology**.

**Rename Environment** preserves KPI contexts, weights, thresholds and source filters. Historical numeric results stay unchanged; supported result views can display the current environment name.

**Delete Environment** removes its contexts from the draft. Keep at least one environment and a positive overall allocation. Names must be unique, ignoring case; **Combined** is reserved.

> [!WARNING]
> **Copied thresholds need review for their new context.** The initial Walk environment has zero points and City-derived rules. Validate it before assigning benchmark points.

#### Environment allocation

| Edit mode | Effect |
| --- | --- |
| **Points** | Set the environment's absolute allocation |
| **Weight (%)** | Change its share while preserving the grand total and redistributing other environments proportionally |
| **Distribute points keeping percentages** | Allocate a chosen total using a reference environment's relative KPI shares |

Distribution changes points, not formulas or thresholds. Relative shares can be edited and retained even when an environment has zero points.

### Editing, replacing, adding and removing KPIs

#### Edit a definition

1. Select the environment.
2. Expand the pastel red **KPI Definitions, Scoring & Thresholds** subpanel.
3. Edit the definition and its environment-specific scoring settings.
4. Save the complete methodology, then calculate or recalculate a job.

| Setting | What it controls |
| --- | --- |
| **Code** | Stable identity and priority references |
| **KPI / Category** | Display labels and grouping |
| **Source** | Data, Voice or Speech CDR rows |
| **Formula / filters** | Measurement and eligible source rows |
| **Direction** | Whether higher or lower measurements are better |
| **Mapping** | Linear, Quadratic or Smooth curve interpolation |
| **KPI Type** | Reliable / Diff display classification |
| **Max points / weight** | The KPI's contribution to the environment |
| **Thresholds / score anchors** | Measurement boundaries and normalized score awarded at each boundary |

KPI Type is descriptive: it does not change the formula, mapping or GAP arithmetic. Calculation basis is read-only information derived from the formula; it does not set the denominator.

#### Points and weights

- **Points:** edit a KPI's absolute maximum.
- **Weight (%):** edit its environment share; the environment total stays fixed and other KPI shares adjust proportionally.
- **Global weight:** read-only KPI points divided by the total points across all environments.

Category totals refresh from their KPI allocations. Setting a KPI to zero points keeps its definition without adding a scoring contribution.

#### Add, move, replace or remove

Category controls move whole categories or insert a category below the current one. KPI row controls insert a definition below that row, move it within its category or delete it.

To replace a KPI, revise its label, formula, filters, source, thresholds and points. If you add a replacement as a new row, remove the old contribution deliberately to avoid counting both.

**Example:** replace `PCT90(Mean_Data_Rate)` with `AVG(Mean_Data_Rate)`, rename the KPI to mean throughput and review its thresholds. Keep or change its FDTT/DL/Completed filters intentionally.

Codes remain stable when rows move. New KPIs receive the next unused K number; deleted codes are not recycled. Renaming a code in the editor remaps its saved priority reference. When editing JSON manually, update `gap_priority` references too.

#### Hierarchy and priorities

The hierarchy contains **Operator**, **Vendor**, **Region**, **City** and **Campaign** exactly once. Its order controls the grouping/display sequence; jobs choose which additional levels to include.

The priority editor supports moving a KPI up/down, to the first/last position or to a specified position. Category membership remains visible.

> [!NOTE]
> **GAP priorities are saved settings.** Current individual GAP tables sort by signed GAP, while All Operators uses KPI definition order. Editing priority does not change these display orders.

#### Supported expression language and limits

| Operation | Example |
| --- | --- |
| Average | `AVG(Call_Setup_Time)` |
| Median | `MEDIAN(field)` |
| 90th percentile | `PCT90(Mean_Data_Rate)` |
| Sum / count | `SUM(field)` / `COUNT(field)` |
| Supported conditional ratio | `100 * SUM(Call_Status == "Completed") / COUNT(Call_Status)` |

Conditions support the implemented comparisons, `AND`, `CONTAINS(...)` and `IS NOT NULL`. Filters use JSON objects; values inside a field select its permitted source values:

```json
{
  "Session_Type": ["CALL", "MultiRAB CALL"],
  "Call_Status": ["Completed", "Dropped"]
}
```

The Interactivity packet-error formula has explicit IFNULL behavior for lost, discarded, corrupted and unsent packets. Missing optional loss components count as zero in that formula. `Packets_Sent` remains required and its sum must be positive; missing or zero sent packets produce N/A.

> [!CAUTION]
> **Formulas use a supported expression allowlist.** Arbitrary Python, SQL or Tableau expressions are not executed. Other absent source fields do not become optional because the packet-loss formula supports IFNULL.

Limits: **256 KPIs**, **32 environments** per methodology and **64 methodologies** per workspace. New fields or unsupported operations require engine support, not just a JSON edit.

### Portable JSON reference

#### Envelope and required content

Exchange format **version 3** uses the same envelope for one methodology or a complete collection. Files exported before the rename to DriveTest Analyzer, with the format `dashboard-analytic-scoring-configuration`, are still accepted. A one-methodology export has one item in `profiles`; Admin exports can contain all items.

The internal JSON names `profiles` and `active_profile_id` remain format identifiers. In the interface, these entities are called **methodologies**, and the active ID identifies the default.

The following minimal example contains one KPI. A complete benchmark must include all intended KPI definitions and a context for every configured environment.

```json
{
  "format": "drivetest-analyzer-scoring-configuration",
  "version": 3,
  "active_profile_id": "netcheck-2026",
  "profiles": [
    {
      "id": "netcheck-2026",
      "name": "Netcheck 2026",
      "configuration": {
        "version": "2026Q2",
        "title": "NetCheck 2026 scoring",
        "scope": {
          "environments": {
            "Drive - City": {
              "source_filters": {"G_Level_1": "Drive", "G_Level_2": "City"}
            }
          }
        },
        "metrics": [{
          "code": "K1",
          "category": "CLASSIC CALLS",
          "kpi": "CALL SUCCESS RATIO [%]",
          "source_kind": "voice",
          "direction": "higher_is_better",
          "kpi_type": "Reliable",
          "calculation": {
            "formula": "100 * SUM(Call_Status == \"Completed\") / COUNT(Call_Status)",
            "filters": {"Session_Type": ["CALL"]}
          },
          "contexts": {
            "Drive - City": {
              "max_points": 650,
              "thresholds": {"low": 85, "medium": 98, "high": 100, "ultra": null}
            }
          }
        }],
        "gap_priority": [],
        "aggregation_hierarchy": ["Operator", "Vendor", "Region", "City", "Campaign"]
      }
    }
  ]
}
```

#### What is stored or derived?

| Field | Meaning |
| --- | --- |
| `configuration.version` | Methodology revision; separate from exchange format version |
| `title` | Optional editable description |
| `scope.environments` | Names, explicit source filters and optional display names |
| `metrics` | Nonempty collection of identified KPI definitions |
| Metric `calculation` | Formula and source filters; the formula determines the denominator |
| Metric `mapping_method` | `piecewise_linear`, `piecewise_quadratic` or `piecewise_smoothstep` |
| Metric `contexts` | Each environment's thresholds, maximum points and optional score anchors |
| `interpolation` | Optional default score anchors |
| `aggregation_hierarchy` | All five dimensions in order |
| `gap_priority` | KPI code order; removed codes are dropped and new codes appended |
| `next_kpi_number` | High-water mark for generated codes |

Environment totals and positive-point relative weights are derived from KPI maximum points, so exports do not duplicate them. Relative shares for zero-point environments are retained.

Reference filenames, workbook cells, denominator descriptions and Tableau grouping keys are not needed for an operational methodology and are omitted. Optional mapping/anchor settings use supported defaults when omitted; retain explicit settings when customized.

Version-2 exchange envelopes must be replaced with a new export. Existing supported workspace records are normalized on read; this is different from accepting an obsolete exchange envelope.

> [!IMPORTANT]
> JSON import/export, ZIP configuration packages, transfers and configuration backup/restore use the same methodology format. They do not transfer CDR-dependent job results unless the workspace database is included.

### Reference Prep flow and implemented calculation

#### From raw rows to points

1. Apply environment source selectors and job filters.
2. Group raw rows by the selected Operator/Vendor/Region/City/Campaign levels.
3. Calculate each KPI from its formula and source filters.
4. Map the measurement to a normalized score between 0 and 1.
5. Multiply by the KPI's configured maximum points.
6. Sum weighted points for categories, environments and total scoring.

Operator aliases use the mapping snapshot saved with the job. When Campaign is not selected as an aggregation level, campaign rows are pooled before KPI calculation.

Unlike the source Prep flow's inner joins, the application preserves groups with missing measurements as N/A and reports their incomplete coverage.

#### Mapping methods and anchors

For normalized position `t` between adjacent measurement thresholds:

| Method | Interpolation fraction |
| --- | --- |
| **Linear** | `t` |
| **Quadratic** | `t²` |
| **Smooth curve** | `3t² − 2t³` |

All methods preserve the configured threshold anchors, direction and score limits. Mapping and Direction are separate settings. The original NetCheck definitions use Linear.

Default NetCheck anchors without Ultra are **Low = 0%**, **Medium = 80%**, **High = 100%**. With Ultra, K20/K25 use **High = 90%** and other supported mappings use **95%**; **Ultra = 100%**. Per-context anchors are editable.

Dynamic best-value Ultra thresholds use all operators in the selected comparison context. Selecting a different operator scope can therefore change a dynamic threshold.

#### Combined environments and coverage

All Environments sums configured maxima and separately calculated environment points. Missing measurements do not reduce the configured benchmark or redistribute their allocations.

Global raw KPI values are recalculated from pooled source rows across configured environments. They are not averages of environment KPI measurements. Zero-point environments can contribute raw measurements without adding weighted points.

> [!WARNING]
> **A zero-point environment does not cause incomplete weighted scoring.** A missing positive-point contribution does. Historical jobs without saved global raw measurements require recalculation to display those values.

#### GAP calculations and aggregates

GAP subtracts **reference weighted points** from **compared operator weighted points** within the same context. Vendor matching can use the reference operator's All group; other context levels still match.

| Result | Calculation |
| --- | --- |
| KPI GAP | Operator KPI points − reference KPI points |
| Scoring category/final GAP | Mean of valid original KPI comparisons |
| GAP table footer | Sum of valid KPI GAPs in each column |
| Individual PPT Average KPI GAP | Mean of valid displayed KPI GAP cells |
| Individual PPT Average total KPI GAP | Mean of the displayed columns' KPI sums |

The overall KPI mean uses original KPI rows, not an unweighted mean of category means. No aggregate applies KPI weights a second time.

For All Environments, only valid environment contributions common to both sides are compared. A subset is marked partial; disjoint coverage or a missing reference gives N/A. Column totals with missing/partial contributions carry an asterisk.




## Persistence and exports

### Results exports

| Action | Contents |
| --- | --- |
| **Scoring CSV** | Expanded scoring results, category subtotals and totals |
| **GAP CSV** | Expanded GAP results and their existing numeric fields |
| **PowerPoint** | Saved results with editable tables and charts, covers and environment transitions |
| **Word** | The same report as the PowerPoint, one landscape page per slide exactly as in PowerPoint (rendered with LibreOffice, included in the Docker image; without it the slide tables and charts are rebuilt) |

**Export PowerPoint** and **Export Word**, at the top right of the Scoring Calculation panel beside NR Mode, export the selected job like the results tools; a progress dialog stays open while the document is generated. Selecting one environment exports that environment. **All Environments** exports the aggregate and available individual environments. Exports use saved job results; they do not recalculate KPIs.

CSV preserves stored names, numeric values and its schema. Its existing category/final GAP aggregates remain valid-KPI means. The new **Total KPI GAP** footer is a web/PowerPoint display total; it does not redefine CSV GAP fields. `gap_partial` and `gap_environments` identify partial coverage.

### What is in the PowerPoint?

Each environment block contains:

1. Best Network Scoring per Service and per Category.
2. Scoring per Category.
3. Scoring Tables — Summary and Breakdown.
4. All Operators GAP comparison, then individual operator comparisons.

Covers and transitions show white titles and field labels, with **bold yellow filter, aggregation and campaign values**. The **Campaigns:** label is bold white. Long lists can be shortened visually without changing the calculation.

The export follows Scoring Tables GAP visibility and column placement. Dedicated GAP slides remain included. Individual slides include the Priority arrow, mean KPI GAP and column-averaged total; every GAP table includes its column totals and color scale.

### Dense-chart options

| Chart | Export asks whether to split when… |
| --- | --- |
| Best Network | More than 20 bars |
| Scoring per Category | More than 40 bars |

Keep all bars for one slide, or split for more readable charts. Splitting preserves complete category groups where applicable and a common Best Network scale. Scoring bar labels use smaller integers above 40 bars and are hidden above 70. Small stacked segments may omit labels; their values remain in the editable chart.

> [!TIP]
> Narrow filters or split charts when many combinations make labels too small. Dense tables keep their combinations together, so reducing the scope also improves table readability.

### Save, export and backup are different

| Action | Purpose |
| --- | --- |
| **Save Methodology** | Commit edits to the workspace database |
| **Export Methodology (JSON)** | Download the selected saved methodology |
| **Admin → Import / Export → Scoring Configuration** | Transfer the complete methodology collection and its default |
| **Workspace database backup / restore** | Preserve methodologies, CDR-dependent jobs, results and shared selections |

Configuration-only packages do not carry scoring jobs or workspace-local CDR selections. Workspace duplication, database exports, transfers and ZIP database backups preserve jobs with the workspace database.

After a restart, interrupted jobs are retained as failed and can be recalculated. After CDR processing, compatible Data/Voice/Speech companions can trigger a default Operator calculation. **Recalculate Scoring** in Workspace opens the module with compatible selected inputs.

## Troubleshooting

| Symptom | Check or action |
| --- | --- |
| No selectable CDRs | Verify workspace, NR Mode and ready processing status |
| Calculate is disabled | Read the yellow notice; complete each campaign's three source types or use Recalculate for a matching job |
| Expected vendor/city choices are missing | Check mappings and the selected CDRs; reprocess older incomplete catalogues |
| GAP is N/A* | Verify the reference and matching context, including common valid environment coverage |
| Maximum achievable points differ between columns | Read the excluded KPI list for each combination; unavailable contributions can differ |
| Results differ from another report | Compare methodology revision, filters, aggregation, thresholds and coverage |
| CDR changed during calculation | Wait for processing/mapping to finish and recalculate |
| Older All Environments KPI values are N/A | Recalculate to save pooled global measurements |
| Job failed after interruption | Recalculate the existing job; delete it only if no longer needed |

> [!NOTE]
> **NR Mode selects the dataset universe.** It does not supply a different SA methodology automatically. Validate copied or customized environment rules before using them for a new benchmark.

## Supported KPI allocation

The initial NetCheck 2026 methodology contains 32 KPIs. The following source notes and allocation table describe the original rules; customized methodologies can change them.

### NetCheck 2026 workbook verification

#### Source documents

| Reference | Role |
| --- | --- |
| `Netcheck_Score_Mapping_2026Q2_BestNetwork_Drive_City_Road.xlsx` | Thresholds, mapping anchors and maximum points |
| `Join_NC_CDR_KPIsv3_all_UK.tfl` | Source formulas, filters and aggregation reference |
| `20260416 NET CHECK Press Benchmarking Package for Mobile Networks.pdf` | Benchmark methodology context |
| Earlier example PPT | Presentation layout reference |

The Git-ignored local `assets/scoring/netcheck_2026.json` is an optional reference import. It is not distributed or loaded automatically. Workspace rules remain authoritative.

#### Initial allocation and matching

The workbook contains 32 KPI definitions in each of DriveCity and DriveConnectionroad, rows 4–35. Its maximum allocations were checked against the extracted rules; City totals **650** and Road **350** points.

The current Road selector uses **G_Level_1 = Drive**, **G_Level_2 = Connecting Roads**. The workbook sheet name is provenance, not the current source selector. Known legacy Road definitions are corrected without changing their points; explicit customized names/selectors are preserved.

Walk is a zero-point extension with City-derived starting thresholds. It needs validation before assigning points.

#### Documented differences

> [!NOTE]
> **Reference documents are not interchangeable numerical baselines.** Match raw inputs, revision, filters, operator scope, aggregation and coverage before comparing results.

- Dynamic City best-value Ultra ranges in the workbook exclude some operators; the application uses all selected operators, following the best-achieved definition.
- Two City P90 operator formulas use High = 95% while the common formulas and Road use 90%. The application consistently uses 90% for K20/K25.
- The PDF's Drive/Walk allocation totals 675 points; this mapping uses the workbook's 1,000-point City/Road allocation.
- The earlier example PPT uses different Q4 weights; it supplies layout guidance, not a numeric golden for the current mapping.
- POLQA low-quality calculation uses **LQ <= 1.6**, despite the source label. Call setup threshold uses **> 10 seconds**, rather than the older example PPT's > 15 seconds.

The source Prep flow has 18 aggregation steps and 17 inner joins. The application calculates the supported formulas directly from processed rows and retains missing comparisons visibly.

Regression fixtures cover representative formulas and mapping examples. Full numerical parity with an external Prep/Excel output still requires matching source data and an independently verified result.

### Per-KPI reference points

This is the **original NetCheck 2026 reference**, not a promise that a customized saved methodology uses these weights. Point values are shown to four decimal places.

| Code | Category | KPI | City points | Road points |
|---|---|---|---:|---:|
| K1 | CLASSIC CALLS | CALL SUCCESS RATIO [%] | 73.4825 | 39.5675 |
| K2 | CLASSIC CALLS | CALL SETUP TIME [s] | 8.6450 | 4.6550 |
| K3 | CLASSIC CALLS | CALL SETUP TIME > 10 s [%] | 4.3225 | 2.3275 |
| K4 | CLASSIC CALLS | POLQA < 1.6 [%] | 22.7500 | 12.2500 |
| K5 | CLASSIC CALLS | POLQA [MOS] | 7.5855 | 4.0845 |
| K6 | CLASSIC CALLS | DISTURBED & IMPAIRED CALL [%] | 15.1645 | 8.1655 |
| K7 | WHATSAPP CALLS | CALL SUCCESS RATIO [%] | 56.8750 | 30.6250 |
| K8 | WHATSAPP CALLS | POLQA < 1.6 [%] | 14.7875 | 7.9625 |
| K9 | WHATSAPP CALLS | POLQA [MOS] | 4.9270 | 2.6530 |
| K10 | WHATSAPP CALLS | DISTURBED & IMPAIRED CALL [%] | 9.8605 | 5.3095 |
| K11 | MULTI RAB | MULTI RAB DATA TRANSFER SUCCESS RATIO [%] | 9.1000 | 4.9000 |
| K12 | TRANSFER | FDFS DL SUCCESS RATIO [%] | 30.4200 | 16.3800 |
| K13 | TRANSFER | FDFS DL TRANSFER TIME [s] | 20.2800 | 10.9200 |
| K14 | TRANSFER | FDFS UL SUCCESS RATIO [%] | 15.2100 | 8.1900 |
| K15 | TRANSFER | FDFS UL TRANSFER TIME [s] | 10.1400 | 5.4600 |
| K16 | TRANSFER | FDTT DL THROUGHPUT > 2Mbit/s [%] | 20.2800 | 10.9200 |
| K17 | TRANSFER | FDTT DL THROUGHPUT > 5Mbit/s [%] | 25.3500 | 13.6500 |
| K18 | TRANSFER | FDTT DL THROUGHPUT > 20Mbit/s [%] | 25.3500 | 13.6500 |
| K19 | TRANSFER | FDTT DL THROUGHPUT > 100Mbit/s [%] | 15.2100 | 8.1900 |
| K20 | TRANSFER | FDTT DL THROUGHPUT P90 [Mbit/s] | 15.2100 | 8.1900 |
| K21 | TRANSFER | FDTT UL THROUGHPUT > 1Mbit/s [%] | 10.1400 | 5.4600 |
| K22 | TRANSFER | FDTT UL THROUGHPUT > 3Mbit/s [%] | 12.6750 | 6.8250 |
| K23 | TRANSFER | FDTT UL THROUGHPUT > 10Mbit/s [%] | 12.6750 | 6.8250 |
| K24 | TRANSFER | FDTT UL THROUGHPUT > 20Mbit/s [%] | 7.6050 | 4.0950 |
| K25 | TRANSFER | FDTT UL THROUGHPUT P90 [Mbit/s] | 7.6050 | 4.0950 |
| K26 | HTTP/HTTPS BROWSING | BROWSING TIME TO 1MB [ms] | 33.8000 | 18.2000 |
| K27 | HTTP/HTTPS BROWSING | BROWSING SUCCESS RATIO [%] | 50.7000 | 27.3000 |
| K28 | VIDEO STREAM | VIDEO STREAMING SUCCESS RATIO [%] | 54.0800 | 29.1200 |
| K29 | VIDEO STREAM | VIDEO STREAMING TTFP >= 10 s [%] | 3.3800 | 1.8200 |
| K30 | VIDEO STREAM | VIDEO STREAMING IRRITATING EXPERIENCE [%] | 27.0400 | 14.5600 |
| K31 | INTERACTIVITY | INTERACTIVITY PACKET ERROR RATIO [%] | 5.0700 | 2.7300 |
| K32 | INTERACTIVITY | INTERACTIVITY MEDIAN RTT [MS] | 20.2800 | 10.9200 |
