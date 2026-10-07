# Scoring & GAP Analysis

Calculate KPI scores from processed Data, Voice and Speech CDRs, then compare each operator with a reference operator. Results belong to the workspace and do not require a Dashboard or Report Template.

Each job calculates the NetCheck **Best Network** scoring, which rates every KPI of the methodology. When the methodology has Most Reliable points, the job also shows the **Most Reliable** scoring, which rates a subset of KPIs with its own maximum points, with the same CDRs, filters, aggregation and GAP reference (see [Most Reliable Network scoring](#most-reliable-network-scoring)).

> [!NOTE]
> **Start with a saved methodology.** It defines the environments, KPI formulas, thresholds and maximum points. The selected job keeps a snapshot of these rules.

## Choose your task

| I want to… | Go to |
| --- | --- |
| Calculate or recalculate a comparison | [Calculate and review](#calculate-and-review) |
| Understand filters and aggregation | [Filters and aggregation](#filters-and-aggregation) |
| Read scores, GAPs and coverage warnings | [Results and workspace settings](#results-and-workspace-settings) |
| Show or configure the Most Reliable scoring | [Most Reliable Network scoring](#most-reliable-network-scoring) |
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
2. Choose the aggregation levels (Operator, Vendor, Region, **Cluster**, City and Campaign, in the order of the aggregation hierarchy). **Operator** is always included; additional levels split the results into separate combinations. Cluster needs CDRs with a `Cluster` column, filled by the source CDR or by a Cluster mapping.
3. In **GAP reference operator**, select the operator to compare against. The initial reference is **EE**.
4. Choose the saved **Scoring Methodology** beside Calculate and Recalculate.

The aggregation hierarchy determines the order of the filter controls and aggregation headers. It is an application setting shared by every workspace and methodology. **Aggregation hierarchy**, at the right of the Aggregation levels, opens a dialog to reorder it; editors save it for everyone. The initial order is **Operator → Vendor → Region → Cluster → City → Campaign**, and calculated jobs keep the order they were calculated with.

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

The **Operator_Vendor** selector filters the `<Operator>_<Vendor>` identity, **Vendor_Operator** the same identity as `<Vendor>_<Operator>` and the **Vendor** selector the vendor alone, using cached per-CDR values; **Cluster** follows Region and **City** offers **Main Cities** first. Choices appear in this order: real vendors, Ericsson_Mixed (and the former Mixed Vendor), Non-Ericsson_Mixed (and the former Other Vendor), All Vendor(s), then operators without assigned vendors labelled **Operator - All**.

**Operator_Vendor** and **Vendor_Operator** stay in sync: selecting values in one selects the same identities in the other. The Scoring report scenarios of Reporting Jobs follow the same rule.

Selecting **Ericsson** and **Huawei** includes only those vendor identities from the selected operators. To include an operator with no assigned vendor, also select its **Operator - All** choice, or leave the Vendor filter unrestricted. Vendor mapping stores the suffix in `Operator_Vendor` and `Vendor`; legacy operator-only values without it remain supported.

Legacy saved operator-prefixed selections are normalized to vendor names. The **Operator** filter remains independent. When Vendor is an aggregation level, operators without a vendor still display **All** in that level; web and PowerPoint retain the existing comparison and reference behavior.

### How the GAP reference is matched

Each comparison retains the selected environment and aggregation context. For vendor comparisons, the engine tries the same vendor first, then the reference operator's **All** vendor group.

> [!NOTE]
> **EE / All can be the reference for Ericsson, Huawei and other vendor groups.** Campaign, City, Region and other selected levels must still match. The fallback does not compare different cities or campaigns.

No matching reference or no common valid environment contribution produces **N/A***.

Filter choices use cached CDR catalogues. If an older CDR lacks expected choices, reprocess it to refresh its catalogue.

## Results and workspace settings

### Choose a scoring

The **Scoring** selector, beside Environment, switches the tables, charts, GAP analysis, notes and CSV exports between **Best Network** and **Most Reliable**. It appears when the job's methodology has Most Reliable points; otherwise the job shows only Best Network. The browser remembers the choice for the session.

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

**Campaign Comparison** appears below the tables when Campaign is an aggregation level with at least two campaigns. For each operator and each combination of the other levels, it lists every KPI with its value and points in the two latest campaigns and **Δ Points** (latest minus previous), from the largest loss to the largest gain in a red–green scale, with the total **Scoring Points Gap**. Choose the comparison in its selector.

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

#### KPI GAP Profile

Below the GAP tables, **KPI GAP Profile** first chooses the location (for example **City: London**, when the results have several) and then one or more **Operators** (all of them by default; choosing an operator in **GAP comparison** above shows that one, and GAP comparison follows a single chosen operator). Each chosen operator is shown in two tables, as in the NetCheck reports. The location and operators are shared with the **Points Lost Map**, and both are kept when the page is reloaded (opening the page again starts from the defaults):

| Table | Per KPI | Order and bars |
| --- | --- | --- |
| **Gap to Maximum** | KPI maximum points − points scored, per environment and in total | Largest loss first, red bars |
| **Gap to <reference>** | Operator points − reference points, per environment and in total | Lowest GAP first, red bars below zero and green above |

The columns are the environments of the selected environment (each environment of All Environments) and **Total KPI**. Every column has its own data bars, which fade from the colour to white like Excel data bars, with the value written over them. In the Best Network scoring, the KPIs of the Most Reliable scoring are underlined. The note below names the operator's total points lost and its total GAP to the reference.

#### Points Lost Map

Below the KPI GAP Profile of All Environments, **Points Lost Map** shows where each operator loses its scoring points, like the NetCheck points-loss slides. It uses the location and **Operators** of the KPI GAP Profile (choosing them in either section chooses them in both; several operators show their maps side by side), and adds the **Analysis**: **Per City**, **Per Region** or **Per Cluster** (an option without data in the results, such as Per Cluster without Clusters, is shown disabled). Drag a rectangle over a map to zoom into it, or use the zoom buttons (zoom in, zoom out, whole map) shown while the pointer is over the map.

| View | Map | Ranking |
| --- | --- | --- |
| **per City** | The UK **ITL3 areas** (the NUTS3 level) coloured from yellow to red by the points lost in each one; hover an area for its points | The cities (`City`, or `G_Level_4`) and Connecting Roads routes (for example *Sheffield to Leeds*) that lose most, with their points and share |
| **per Cluster / Region** | The polygons of the workspace's **Clusters** or **Region Mapping** dataset applied to the CDRs, coloured the same way | The clusters or regions that lose most |

How the points are placed: each KPI loses its maximum points minus the points scored, and the loss is shared among the tests that cause it. For ratio KPIs every test that misses the KPI (a failed call, a POLQA below 1.6, a transfer below its threshold…) weighs one; for averages, medians and P90 each test weighs what it misses the KPI's High threshold by; for packet loss, the packets lost. Each test belongs to the City of its CDR row and to the ITL3 area that contains its coordinates, so the City ranking and the ITL3 map add up to the same total. The map uses the same points as the selected scoring (Best Network or Most Reliable), and jobs calculated before this map existed must be calculated again to show it.

The ITL3 boundaries are bundled with the application (Office for National Statistics, *International Territorial Level 3 (January 2025) Boundaries UK BUC*, Open Government Licence v3.0). To map your own clusters, import a Clusters GeoJSON in Workspace Management and apply it to the CDRs before calculating: the job keeps a simplified copy of its polygons.

### Scoring Charts

| Chart | Use it to… |
| --- | --- |
| **Best Network / Most Reliable Network Scoring per Service** | Compare total points and Data/Voice contributions; Data stacks below Voice |
| **Best Network / Most Reliable Network Scoring per Category** | Compare category contributions within each operator/context stack |
| **Best Network / Most Reliable Network Scoring per Category (Breakdown)** | Compare operators directly within each category |
| **Maximum score allocation donuts** | Inspect configured environment, service and category maxima and shares |
| **Scoring per City / Cluster / Region** | When City, Cluster or Region is an aggregation level with 2 to 12 values: one card per value with each operator's Voice and Data points and its total, labelled with the operator names of the mapping table (hover a bar for its points) |
| **Scoring Trend** | When Campaign is an aggregation level with more than four campaigns: each operator's total points per campaign, one line per operator |

Voice and Speech KPIs contribute to **Voice**; Data KPIs contribute to **Data**, regardless of category names. Allocation donuts show **maximum available allocation**, not earned scores. Chart titles and donuts follow the selected scoring.

Hover bars, segments, totals or donut sectors for values and context. Double-click a chart, a map or a table of Scoring Tables and GAP Analysis to open it larger, taking the whole screen but 5% on each side. Charts and maps zoom into a rectangle dragged with the mouse, or with the zoom buttons (zoom in, zoom out, whole view) shown while the pointer is over them, also in the larger view. Dense web charts scroll horizontally. Operator Mapping supplies labels, order and colors.

A single aggregation level uses normal axis labels; multiple levels use separate header rows. Campaign labels display year-quarter, such as **2026-Q1**, while stored campaign names and CSV identifiers remain unchanged.

The cards follow City first, then Cluster, then Region, and group the other levels: with several campaigns, one set of cards per campaign shows the latest one. In All Environments each card adds the environments measured in that location and scales them to the full maximum (1,000 points in NetCheck 2026), so a city measured only in Drive - City is comparable with the others, as the NetCheck per-city rankings do; the blue panel says so and gives the Voice and Data maxima. A single environment shows its own points. The trend offers one series per combination of the other levels in its selector and uses the same points as the cards.

### Incomplete coverage and achievable scoring

The pale yellow **Calculation notes** card lists affected combinations, missing KPI names and the **exact maximum achievable score** after excluding their unavailable contributions.

> [!WARNING]
> **Missing points are not redistributed.** An incomplete result keeps the original weights and configured benchmark maximum. Available contributions are not scaled up to a complete score.

**Environments without results in any series are scaled.** When the filters leave an environment without results for every operator and series of the calculation (for example, City = London only covers Drive - City), the Combined scores use the environments with results and scale them to the full maximum scoring: an environment without results gets 0 points and the others share its points in proportion, the same for every operator, so GAPs stay comparable. An orange **Scaled results** card explains which environments were scaled and the factor applied; scaled values are not marked as incomplete. The *Maximum score per environment* donuts show the configured points of every environment struck through beside the points finally allocated, and the PowerPoint and Word exports show the same notice in orange on their first page. When an environment has results in any series it is never scaled, and the series without it keep their partial score and their notes. Saved jobs are scaled when they are opened, without calculating them again.

Example: **VF_UK / Samsung / Q1: maximum 583.2645 of 650 points**, with the unavailable KPI names listed below. Another campaign can have a different achievable maximum because different KPIs are missing.

- Incomplete numeric values appear **in bold red with `*`**.
- Unavailable values appear **as N/A*** in the same style.
- Total KPI GAP sums available contributions and carries `*` when a contribution is missing or partial.
- All Environments GAP uses valid environment contributions common to both sides. A subset is partial; no common contribution is unavailable.
- Tooltips explain partial GAP coverage; PowerPoint slide notes include the coverage details.

All Environments raw KPI values are calculated from pooled source rows, not averaged from environment KPI values. Older jobs without these saved measurements show N/A until recalculated. Weighted scoring points still sum the separately calculated environment contributions.

## Methodology

A methodology contains the complete environment, KPI, weighting, threshold and priority setup. Open **Workspace Config → Scoring & GAP Analysis Setup** to edit it; the **Scoring Methodologies** shortcut of the Calculation and Results panels opens it directly. The aggregation hierarchy is not part of a methodology (see [Set filters, aggregation and reference](#3-set-filters-aggregation-and-reference)).

### Named methodologies and portable JSON

Open **Workspace Config → Scoring & GAP Analysis Setup**. Select a methodology or use **Create Methodology** / **Duplicate Methodology** to prepare another one.

The selector's name identifies the methodology. **Methodology title** is an optional editable description preserved in transfers.

#### One complete save

The toolbar and the sibling panels offer the same **Save Methodology** action:

| Panel | Settings included in the save |
| --- | --- |
| **Methodology Environments** | All environments, allocations, KPI specifications and thresholds |
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
| **KPI Type** | Reliable / Diff classification; Reliable KPIs form the Most Reliable scoring |
| **Max points / weight** | The KPI's contribution to the environment in the Best Network scoring |
| **Most Reliable points** | The maximum points of a Reliable KPI in the Most Reliable scoring; editable only on Reliable KPIs |
| **Thresholds / score anchors** | Measurement boundaries and normalized score awarded at each boundary |

KPI Type does not change the formula, mapping or GAP arithmetic; it only decides which KPIs take part in the Most Reliable scoring. Calculation basis is read-only information derived from the formula; it does not set the denominator.

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

#### Priorities

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

### Most Reliable Network scoring

NetCheck publishes two rankings. **Best Network** rates every KPI. **Most Reliable** rates only the reliability KPIs (the KPIs marked with `*` in the NetCheck reports, whose KPI Type is **Reliable**), with its own maximum points, and uses the same formulas, thresholds, score anchors and mapping as Best Network: each KPI keeps its normalized score and only its maximum points change.

| | Best Network | Most Reliable |
| --- | --- | --- |
| KPIs | Every KPI with Max points | Only KPIs whose **KPI Type** is **Reliable** |
| Points of a KPI | Normalized score × Max points | Normalized score × Most Reliable points |
| Thresholds, anchors, mapping | The methodology's | The same |
| GAP | Compared − reference Best Network points | Compared − reference Most Reliable points |

#### Configure it

1. Open **Workspace Config → Scoring & GAP Analysis Setup** and the methodology.
2. In **KPI Definitions, Scoring & Thresholds**, set **Type** to **Reliable** for the KPIs of the Most Reliable scoring (the NetCheck 2026 methodology already does) and enter their **Most Reliable points** in each environment (see [Most Reliable reference points](#most-reliable-reference-points)). The column can only be edited on Reliable KPIs. The line above the table counts the Reliable KPIs and their points in the selected environment and in all environments, and warns about Reliable KPIs without points.
3. **Save Methodology**, then calculate or recalculate the job.

Most Reliable points are part of the methodology: changing them gives the methodology a different identity, so **Calculate Scoring** creates a new job and **Recalculate** updates a selected one. The Most Reliable results are derived from the saved KPI scores of the job, so they never read the CDRs again. A new environment or a new KPI starts without Most Reliable points. A KPI whose Type is not Reliable never takes part, even if it had Most Reliable points (they are dropped when the methodology is saved).

Most Reliable points copied with two decimals can miss an environment's total by a few hundredths (650.02 for 650): when the Most Reliable total of an environment is within 0.1 points of its Best Network total, its Most Reliable points are scaled to match it exactly.

> [!NOTE]
> **Environments without Most Reliable points contribute nothing to it.** The Most Reliable maximum of an environment is the sum of its KPIs' Most Reliable points; All Environments adds them, and [environments without results are scaled](#incomplete-coverage-and-achievable-scoring) the same way as in Best Network.

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
              "most_reliable_points": 650,
              "thresholds": {"low": 85, "medium": 98, "high": 100, "ultra": null}
            }
          }
        }],
        "gap_priority": []
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
| Metric `contexts` | Each environment's thresholds, maximum points, optional score anchors and optional `most_reliable_points` |
| `interpolation` | Optional default score anchors |
| `gap_priority` | KPI code order; removed codes are dropped and new codes appended |
| `next_kpi_number` | High-water mark for generated codes |

Environment totals and positive-point relative weights are derived from KPI maximum points, so exports do not duplicate them. Relative shares for zero-point environments are retained.

`most_reliable_points` is optional; omitted or 0 leaves the KPI out of the Most Reliable scoring of that environment. Files without it are still imported and keep their identity.

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
| **Export to CSV** above the Scoring table | The scoring table shown: expanded results, category subtotals and totals of the selected scoring and environment |
| **Export to CSV** above the GAP table | The GAP table shown: expanded GAP results and their existing numeric fields of the selected scoring and environment |
| **Generate Scoring Report (PPT/Word)** (Calculation panel) | A report of one or more scenarios chosen in the report editor, from the CDRs, NR Mode, methodology and GAP reference selected in the Calculation panel |
| **Export Selected Scoring Report (PPT/Word)** (Results panel) | The selected job as it was calculated (its CDRs, aggregation levels and filters), with editable tables and charts, covers and environment transitions, for both scorings; it only asks for PowerPoint or Word |
| **Word** | The same report as the PowerPoint, one landscape page per slide exactly as in PowerPoint (rendered with LibreOffice, included in the Docker image; without it the slide tables and charts are rebuilt) |

**Generate Scoring Report (PPT/Word)** opens the **report editor** (see [Report scenarios](#report-scenarios)) and calculates its scenarios from the CDRs, NR Mode, methodology and GAP reference selected in the Calculation panel. **Export Selected Scoring Report (PPT/Word)** exports the selected job without the editor. A progress dialog stays open while either document is generated.

### Report scenarios

A report has one or more **scenarios**, in order: for example *National*, then *London*, then the *Main Cities*, then by Vendor. Every scenario uses the CDRs, NR Mode, methodology and GAP reference selected in the Calculation panel with its own **filters** (Operator, Operator_Vendor, Vendor_Operator, Vendor, Region, Cluster, City with **Main Cities**, Campaign) and **aggregation levels**. Each filter list has a search box that narrows the values as you type, **Select All / None** for the listed values, and closes when you click outside it or open another one. Its **All** option keeps no restriction, so the scenario always includes every value of the CDRs when the report is generated, also values that appear in later CDRs (for example a new Operator); **Main Cities** checks the workspace main cities and uses that list when the report is generated. The values stay editable with All or Main Cities checked: changing one keeps exactly the values checked. A closed list shows one chosen value by name and several by their number (for example `2/4 selected` or `Main Cities (5/12)`; hover it to see the values); campaigns are shown with the workspace [Campaign Maps](workspace-config.md#campaign-maps). When the document is generated, each scenario reuses an identical saved scoring job or calculates it, so it can take longer the first time. An aggregation level with a single value (for example **Campaign** when the CDRs hold one campaign, or **City** filtered to one city) splits nothing, so it is left out of the scenario, as it is of every chart, table and document of Scoring & GAP Analysis.

For each scenario and each scoring (**Best Network** and **Most Reliable Network**, which can be left out), choose:

| Group | Options (default) |
| --- | --- |
| Environments | **All Environments only** (default) or All Environments and each environment |
| Scoring Charts | Scoring per Service, per Category and per Category (Breakdown), the per City / Cluster / Region cards and the scoring trend (all on) |
| Scoring Tables | Category table and Breakdown table (on), Show KPI values and Show GAP values (off), Campaign comparison (on) |
| GAP Analysis | **Operators to compare** (Vodafone and Three when available; none chosen compares every operator), the table of all the chosen operators, the individual tables against the reference, the KPI GAP Profile and the Points lost per City map (all on) |

With several scenarios, every setting whose value is not the same in all of them (a filter, an aggregation level, a scoring, its environments or one of its options) is highlighted in amber in each scenario, so what changes from one scenario to another stands out; the highlights follow every change.

The document starts with a cover listing the scenarios; each scenario then has a cover per scoring (for example *London — Best Network Scoring*) with its filters, and its slide subtitles name the scenario and the scoring. With All Environments only, the subtitles omit *All Environments*; each environment block names its environment. Show KPI values adds a **Value** column before each Score of the Breakdown tables.

The selector shows the configuration the report was chosen from when the editor opens (while its scenarios are unchanged). The editor's toolbar saves (**Save as…**) and deletes **named configurations** of the workspace, and exports or imports them as JSON. Choosing a configuration in its selector loads it at once, **Default** included (one scenario with the job's filters and aggregation plus **Campaign**, which is left out when there is a single campaign; *Default* is always listed, cannot be deleted and is not available as a saved name). When the scenarios have unsaved changes, choosing another configuration asks first: **Cancel** keeps them, **Discard changes** loads the chosen configuration and **Save as…** saves them before loading it. The last configuration used to generate a document opens again in any later session. Saved configurations and the last one used travel with the **Scoring & GAP Analysis Configuration** in Import / Export, transfers and backups.

Exports use saved job results; they do not recalculate KPIs of existing jobs. Both **Export to CSV** buttons export the selected job.

CSV preserves stored names, numeric values and its schema, with a `cluster` column after `region` for jobs aggregated by Cluster; the Most Reliable CSV has the same columns with the Most Reliable points (`scoring=most_reliable` in the export address). Its existing category/final GAP aggregates remain valid-KPI means. The new **Total KPI GAP** footer is a web/PowerPoint display total; it does not redefine CSV GAP fields. `gap_partial` and `gap_environments` identify partial coverage.

### What is in the PowerPoint?

When the job has a Most Reliable scoring, each scenario contains both scorings: a **Best Network Scoring** section and then a **Most Reliable Network Scoring** section. Slide subtitles name the scoring (and the environment of an environment block, for example *Most Reliable Network — Drive - City*) and slide notes carry the notes of that scoring. Reporting Jobs generate the same document for their Scoring artifact. Without Most Reliable points the document has only the Best Network sections. Cover and transition titles that are wider than the slide are reduced to fit on one line.

Each block contains, as chosen in the scenario:

1. Best Network (or Most Reliable Network) Scoring per Service and per Category.
2. Scoring per Category (Breakdown).
3. Scoring Tables — Summary and Breakdown.
4. All Operators GAP comparison, then individual operator comparisons.

The All Environments block also contains, when they apply and are chosen:

- **Scoring per City / Cluster / Region** after the service chart: a dark blue panel with the maximum points and up to 12 cards with Voice (amber) and Data (teal) stacked bars and the totals, labelled with the operator names of the mapping table, for the latest campaign.
- **Scoring Trend** after the cards: a line chart per combination of the other levels (up to six).
- **KPI GAP Profile** after the GAP tables: one slide per compared operator with the Gap to Maximum and Gap to reference tables and their gradient data bars in every column, for each combination of the other levels, such as each selected City, Cluster or Region (up to twelve; the latest campaign's when there are more). The note names the operator in its colour and the totals in bold.
- **Points Lost per City** after the profiles: one slide per compared operator with the ITL3 map coloured by the points lost and its yellow–red scale, and the cities and routes that lose most as bars (up to 30), with the share of the points lost they account for. Workspaces with Clusters or Region Mapping polygons add a **Points Lost per Cluster** or **per Region** slide. Without ITL3 areas (data outside the UK) the cities are bubbles over the test locations.
- **Campaign Comparison** at the end: the comparison tables of up to eight operator and level combinations, two per slide.

Slide titles are blue, with the part that tells consecutive slides apart in bold: the focus (for example *Best Network Scoring **per City***) or what follows the dash (for example *GAP Analysis — **3 vs EE*** or *Scoring Tables — **Summary***). Subtitles name the scoring and the environment in bold.

Covers and transitions show white titles and field labels, with **bold yellow filter, aggregation and campaign values**. The **Campaigns:** label is bold white. Long lists can be shortened visually without changing the calculation.

The export follows Scoring Tables GAP visibility and column placement. Dedicated GAP slides remain included. Individual slides include the Priority arrow, mean KPI GAP and column-averaged total; every GAP table includes its column totals and color scale.

### Dense-chart options

| Chart | Export asks whether to split when… |
| --- | --- |
| Best Network | More than 20 bars |
| Scoring per Category | More than 40 bars |

Keep all bars for one slide, or split for more readable charts. Splitting preserves complete category groups where applicable and a common Best Network scale. **Scoring per Category (Breakdown)** keeps every category on one slide up to 50 bars and, above that, spreads the categories over as few slides as possible with a similar number of bars each (*Page 1 of 2*), in PowerPoint and Word. Scoring bar labels use smaller integers above 40 bars and are hidden above 70. Small stacked segments may omit labels; their values remain in the editable chart.

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

After a restart, interrupted jobs are retained as failed and can be recalculated. After CDR processing, compatible Data/Voice/Speech companions can trigger a default Operator calculation.

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

### Most Reliable reference points

The NetCheck 2026 Most Reliable scoring rates 10 KPIs with **650** points in Drive - City and **350** in Drive - Connecting Roads (Voice 350, Data 650, **1,000** in total); the KPIs underlined in the NetCheck Q2 2026 report are the same. Each KPI has global points (for example 141.75 for the classic call success ratio) split 65% City and 35% Road, as in Best Network. `Netcheck_Score_Mapping_2026Q2_Mostreliable_Drive_City_Road.xlsx` writes these points by hand rounded to two decimals, which adds up to 1,000.04; neither the workbooks nor the reports give a formula to derive them, so they are part of the methodology. Thresholds and score anchors are the Best Network ones. Enter these values in the Most Reliable points column:

| Code | Category | KPI | City points | Road points |
|---|---|---|---:|---:|
| K1 | CLASSIC CALLS | CALL SUCCESS RATIO [%] | 92.1375 | 49.6125 |
| K4 | CLASSIC CALLS | POLQA < 1.6 [%] | 44.3625 | 23.8875 |
| K7 | WHATSAPP CALLS | CALL SUCCESS RATIO [%] | 61.4250 | 33.0750 |
| K8 | WHATSAPP CALLS | POLQA < 1.6 [%] | 29.5750 | 15.9250 |
| K12 | TRANSFER | FDFS DL SUCCESS RATIO [%] | 63.3750 | 34.1250 |
| K14 | TRANSFER | FDFS UL SUCCESS RATIO [%] | 38.0250 | 20.4750 |
| K16 | TRANSFER | FDTT DL THROUGHPUT > 2Mbit/s [%] | 101.4000 | 54.6000 |
| K21 | TRANSFER | FDTT UL THROUGHPUT > 1Mbit/s [%] | 50.7000 | 27.3000 |
| K27 | HTTP/HTTPS BROWSING | BROWSING SUCCESS RATIO [%] | 84.5000 | 45.5000 |
| K28 | VIDEO STREAM | VIDEO STREAMING SUCCESS RATIO [%] | 84.5000 | 45.5000 |

Regression tests reproduce the workbook's City and Road totals for each operator from its KPI values, within the 0.05 points of its rounding.
