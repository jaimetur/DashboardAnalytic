# Network Insights

Analyse the network behind the measured performance: radio quality (RSRP and SINR), weak-coverage and high-interference areas on a map, observed and inventoried sites, licensed and observed spectrum, and network deployment (NNS, eMOCN scenarios, host networks and RAN vendors). Results are grouped by the dimensions checked in **Group by**; Operator and Campaign are checked by default.

> [!NOTE]
> **Radio views need no extra input.** RSRP, SINR, maps, observed eNodeBs and observed bands come from the processed CDRs. Site inventories and licensed spectrum are optional inputs that complete the Cluster Sites Density, Spectrum and Network Deployment panels.

## Choose your task

| I want to… | Go to |
| --- | --- |
| Run an analysis | [Analysis Selection](#analysis-selection) |
| Compare coverage and interference per Operator | [Overview and RF Quality](#overview-and-rf-quality) |
| Locate weak-coverage or high-interference areas | [Coverage and Interference Maps](#coverage-and-interference-maps) |
| Count sites and eNodeBs | [Cluster Sites Density](#cluster-sites-density) |
| Compare Low, Mid and High (TDD) spectrum | [Spectrum](#spectrum) |
| Count NNS, eMOCN or shared sites | [Network Deployment](#network-deployment) |
| Present RSRP and SINR slides in a Dashboard | [RF Quality template and Dashboard](#rf-quality-template-and-dashboard) |
| Check which CDR fields are used | [Data sources](#data-sources) |
| Know which inputs are still missing | [Pending inputs](#pending-inputs) |
| Export the analysis to PowerPoint or Word | [Export](#export) |
| View and export complete site/cell inventories or deployment counts as CSV | [Network Deployment](#network-deployment) |

## Analysis Selection

1. Open the workspace and the **Network Insights** tab, which follows **Scoring & GAP Analysis**.
2. Choose **NR Mode**. All ready Data, Voice and Speech CDRs of that mode are selected; clear the ones you do not need. **Select All** in each CDR type card selects all its CDRs, and becomes **Select None** to clear them when all are selected.
3. Restrict **Operators**, **Vendors**, **Regions**, **Cities** or **Campaigns** in **Filters:** if needed. Their values load automatically from the selected CDRs; **Main Cities** appears first in Cities when configured. Leaving every value selected applies no restriction.
4. Choose **Technology** (LTE, NR or LTE+NR) and **Group by** (Operator, Vendor, Region, City, CDR type and Campaign).
5. Adjust the thresholds of the selected technology and the **Map grid** size (default 250 m). LTE and NR have their own thresholds because LTE RSRP/SINR and NR SS-RSRP/SS-SINR use different reference signals; LTE+NR shows both pairs.

| Threshold | LTE default | NR default |
| --- | --- | --- |
| Coverage below (low coverage) | -110 dBm | -115 dBm |
| Interference below (high interference) | 0 dB | -3 dB |
6. Press **Analyse Network**. A dialog shows that the analysis is in progress, with the elapsed time, and closes when the results are ready; **Hide** closes it while the analysis continues.

### Grouping

**Group by** accepts several dimensions; they form a hierarchy in the selector order, with Campaign last. Each Overview card, table row, CDF curve and map group is one combination, for example `EE · 2026-Q2`.

- **Operator** is always checked and disabled unless **Vendor** is checked. With Vendor checked, Operator becomes selectable: uncheck it to pool the selected operators by vendor, or keep it to split each operator by vendor.
- **Operator_Vendor** uses the `<Operator>_<Vendor>` identity and **Vendor** the vendor alone: actual vendors, then Mixed, Other and All Vendor(s), then operators without a mapped vendor as **Operator - All**. **Cluster** follows Regions and is also available in **Group by**.
- Curves of the same Operator (or Vendor) share its colour. Campaigns differ by line width: the latest campaign is the thickest and older campaigns are progressively thinner, as in E2E Dashboards. Other secondary groups, such as Region or City, use a different line style.
- The change between the two latest campaigns appears only when Campaign is not a grouping dimension.
- eNodeBs and cells are counted per source operator, also when operators are pooled.

### LTE+NR

**LTE+NR** analyses each technology separately with its own thresholds, so LTE and NR are never pooled: Overview, RF Quality (two CDFs and a table per technology) and the Coverage and Interference Maps show an **LTE** section followed by an **NR** section. Each section includes the samples with measurements of its technology; a sample with both contributes once to each. Select LTE or NR to analyse one technology.

> [!TIP]
> The first analysis of a CDR copies its radio fields into the combined reporting tables and can take a minute. Later analyses of the same CDRs reuse them and the parsed samples, so changing filters, thresholds or the map Operator is fast. Repeating an analysis with the same CDRs and options returns the stored result immediately, also after a restart; it is recalculated when the CDRs, inventories, Operator Maps or Spectrum Holdings change. Stored results live in `.network-insights-cache` beside the workspace database and can be deleted at any time.

Operator names follow the workspace **Operator Maps**, including their colours; rows from ignored CDR sheets are excluded.

## Overview and RF Quality

The **Overview** shows one card per group with the median RSRP, the share of samples below the coverage threshold, the median SINR, the share of samples below the interference threshold, the observed eNodeBs and the number of samples. When the selection contains two or more campaigns and Campaign is not grouped, each indicator shows its change between the two latest campaigns: green when the indicator improves and red when it worsens.

**RF Quality** contains:

- the RSRP and SINR cumulative distributions, one curve per group, coloured by Operator with a line style per secondary group;
- a table per group with median and 10th-percentile RSRP and SINR, the low-coverage and high-interference shares and the quality-class distribution.

| Class | RSRP (dBm) | SINR (dB) |
| --- | --- | --- |
| Excellent | ≥ -80 | ≥ 20 |
| Good | -90 to -80 | 13 to 20 |
| Fair | -100 to -90 | 5 to 13 |
| Poor | -110 to -100 | 0 to 5 |
| Very poor / Bad | < -110 | < 0 |

Values outside physical ranges (RSRP outside -160 to -20 dBm, SINR outside -30 to 50 dB) are treated as missing.

## Export

**Export PowerPoint** and **Export Word**, beside Analyse Network, create a Summary Network Insights of the current selection: the selected CDRs, technology, grouping, thresholds and filters, the RF quality overview with campaign deltas, RSRP and SINR CDFs, coverage and interference maps with their weakest areas, observed and licensed spectrum, both Cluster Sites Density data sources and network deployment. Charts and maps are rendered at full size, so the export takes longer than the on-screen analysis. PowerPoint uses the same Template_CDR_analysis.pptx master, cover and layouts as E2E Dashboards. Table widths follow their headers and values, with wider identity columns and single-line cells; very wide PowerPoint comparisons use metric parts with the Group column repeated. Word uses horizontal pages, increasing their width for wide tables, fixed column widths and repeating single-line headers.

Both formats include every grouped Network Deployment view (eMOCN Scenario, Host Network, Network, RAN Vendor, Region, Subregion, Cluster when polygons or inventory fields are available, Site Type and Band), irrespective of the currently displayed dropdown option. Observed Sites/Cells (from CDRs) and Full Sites/Cells Inventory are excluded from PowerPoint and Word; use their individual or combined CSV exports. With LTE+NR, the overview, CDFs, maps and weakest areas appear once for LTE and once for NR. The same summary is available as a [Reporting](reporting.md) artifact.

## Coverage and Interference Maps

The maps show one group at a time (selected in **Group**) over OpenStreetMap; with LTE+NR, the LTE and NR maps of that group appear in separate sections, each classified with its own thresholds. Samples are grouped into square grid cells of the selected size, and each cell is coloured by its mean RSRP or SINR class. Cells need at least three located samples. Very dense selections use a coarser grid automatically to keep the map readable; the note above the maps shows the grid actually used.

Below each map, the **Weakest coverage areas** and **Highest interference areas** tables rank the cells where at least half of the samples are below the threshold, by the number of affected samples. Select an area (its City) to zoom the map to it, and **Show Whole Area** to return. Hover over a CDF or map to show its zoom controls (−, +, the zoom level and 1:1 to reset), as in E2E Dashboards; drag a rectangle to magnify an area, then drag or use the arrows to pan.

## Network Deployment

This panel reads the cell inventories uploaded as **Vendor mapping** datasets (Vodafone and Three) and counts distinct sites and cells grouped by eMOCN Scenario (for example S0, S1, NNS or S2), Host Network, Network, RAN Vendor, Region, Subregion, Cluster, Site Type or Band. **Cluster** appears below Subregion and is enabled when ready **Clusters — Geospatial** polygons or an inventory Cluster field are available. **Region** and **Cluster** use the names of imported polygons containing each site. Coordinates come from inventory Longitude/Latitude (WGS84), with Easting/Northing (British National Grid) as a fallback. All ready polygon uploads participate; newest uploads take precedence where polygons overlap, and boundary points are included. With polygons present, missing coordinates or unmatched sites are **Not set**. Without polygons for that dimension, Region or Cluster uses the corresponding inventory field if present (including UK "Regional", Engineering Polygon and Regional Optimisation Polygon aliases); inventories without it show totals. Polygon revisions invalidate cached deployment counts. This assigns names and counts identifiers; density per unit area is not calculated. An inventory without the selected column shows its totals instead. Each inventory table has an **Export CSV** button that downloads all its displayed grouping rows and site/cell counts, including the totals fallback. **Export All to CSV** combines every displayed table in one CSV, with Operator, Source_Dataset_ID and Source_Dataset_Name to identify each contribution.

Choose **Full Sites/Cells Inventory** in **View / Group by** to see separate Vodafone and Three tables side by side for the selected operators, each with its own pages of 50 rows (stacked on narrow screens). The first seven columns — **Operator**, **Operator_Vendor**, **Vendor**, **Region**, **Cluster**, **City** and **Technology** — have green backgrounds. Operator uses the workspace operator identity; Operator_Vendor is the `<Operator>_<Vendor>` identity and Vendor the vendor alone from the mapping; inventories with the former Vendor_Only column keep working. City comes from the mapping. Region and Cluster prefer imported polygon names resolved from the inventory site coordinates, falling back to the inventory fields only when no polygons exist for that dimension; unmatched polygon locations remain empty. Their source-header aliases include Vodafone Region, Beacon2Town and Engineering Polygon, and Three UK "Regional", Town and Regional Optimisation Polygon; blank generic columns do not hide populated source attributes. Technology uses LTE/NR, resolved from Technology/RAT, Vodafone's 4G/5G source sheets or Three's LTE ECI format.

The inventory tables include **all uploaded mapping rows**, whether or not their cells appear in the CDRs. **Analysis Selection** filters Operator, Vendor, Region, City and Technology directly against the mapping attributes; Region filters match imported polygon names when Region polygons are present. Selected CDRs, NR Mode and Campaigns do not restrict inventory rows because they describe measurements rather than the deployed inventory. The tables also work without a selected CDR. Operators without a matching uploaded inventory contribute no records.

**Previous** and **Next** navigate the filtered table; horizontal scrolling reveals additional columns. Each table’s **Export CSV** downloads all matching rows and columns for its operator, not only the visible page. The complete CSV is prepared before the download begins to prevent partially exported inventories. **Export All to CSV** combines both operators in one file. Both exports use the selection that generated the displayed tables. Repeated inventory rows remain intact. Missing fields in another operator's inventory appear empty. Source_Dataset_ID and Source_Dataset_Name identify each mapping file, including multiple uploaded versions. All original columns are retained after the highlighted fields; source headers that collide with those fields use a `Source_` prefix so their original values remain available.

Choose **Observed Sites/Cells (from CDRs)**, above Full Sites/Cells Inventory, to list the same per-operator tables from the CDR measurements instead: one row per observed site and LTE cell (Cell Identity; sites without a reported cell appear with an empty Cell_ID) with Operator, Vendor, Region, City, Cluster, Technology, Band, CDR types, Campaigns, Samples, mean coordinates and mean RSRP/SINR. These tables follow the full Analysis Selection, including the selected CDRs, NR Mode, Campaigns and filters. Building them for a new selection takes a few seconds; the result is stored and reused.

Every column header of both tables has a **▾** button with an Excel-style filter: search the column values (with their row counts, under the other active filters), check the ones to keep — **(Blanks)** keeps empty cells — and **Apply**. Filtered columns are highlighted, **Clear N filters** removes them, and the table's **Export CSV** exports only the filtered rows.

CSV file names identify their operators: `_VF` for Vodafone tables, `_3` for Three tables and `_VF_3` for files combining both, for example `site-cell-inventory_VF.csv`, `cdr-observed-sites-cells_3.csv` or `network-deployment-scenario_VF_3.csv`.

Grouped deployment counts and their CSVs retain their inventory-wide scope. Deployment tables and the inventory index are stored in the workspace cache, so switching **View / Group by** is fast until an inventory changes. Existing per-dataset inventory download endpoints remain available for complete source exports. No additional persistent data is created; existing dataset export, transfer and backup/restore workflows continue to carry the mappings.


## Cluster Sites Density

Choose the **Data source** dropdown:

- **Observed Sites/Cells** follows the selected CDRs and Analysis Selection filters. The table counts, per group, the **observed eNodeBs** (distinct LTE eNodeB identities, Cell Identity ÷ 256, that served the measuring devices) and **observed cells**, with the samples per eNodeB. Observed eNodeBs depend on the route and do not equal the deployed sites.

- **Inventory Sites/Cells** reads every ready Vodafone and Three Vendor mapping dataset uploaded in Workspace. It shows distinct sites and cells per operator, deduplicating identifiers across overlapping uploads, plus inventory total cards. These are complete inventory counts, independent of CDR selection and filters. Other operator inventory formats are not currently supported.

A warning card explains that site density per cluster requires cluster polygons imported in Workspace as **Clusters — Geospatial** (GeoJSON, JSON or zipped shapefile). These datasets validate and preserve the boundaries; density per cluster is not calculated yet. **Network Deployment** appears immediately before this panel.

The explanatory note appears only in Observed Sites/Cells mode. A separate yellow **Pending input** card above the cluster-polygon warning lists only operators present in the filtered analysis without a ready inventory. It is hidden when all analysed operators have inventories, before an analysis exists, and in Inventory Sites/Cells mode. PowerPoint and Word include both data sources irrespective of the selected dropdown option; neither view calculates density without cluster polygons.

## Spectrum

**Licensed spectrum** aggregates the MHz configured in [Workspace Config → Spectrum Holdings](workspace-config.md#spectrum-holdings) per Operator into Low (below 1 GHz), Mid (1–3 GHz FDD/SDL) and High (TDD) bands. Without holdings, the panel shows a pending-input notice.

**Spectrum observed in the measurements** shows the share of samples served on each LTE band (from the serving EARFCN or the band of the cell trace) and NR band, with the frequency, duplex mode, class and the most frequent downlink bandwidth. Bandwidths are reported only by CDR Data. Observed bands follow the grouping: keep Operator checked to see each operator's own bands.


## RF Quality template and Dashboard

The existing **NSA - RF Quality (RSRP & SINR)** template and **RF Quality (RSRP & SINR)** Dashboard are workspace content. The application does not install them automatically. Import them from another workspace or create them in the editors. A Dashboard without a saved CDR universe uses the two newest NSA CDRs of each type. The template contains:

Each family (CDF/histograms, averages, classes, thresholds and maps) starts with an **All CDR types** slide. It pools valid Data, Voice and Speech observations per Operator and Campaign; it does not average the three type averages. LTE and NR stay separate, and missing technologies do not contribute samples. The existing type-specific slides follow the aggregate.

- Grouped-bar histogram slides follow each CDF/contour slide for All CDR types, Data, Voice and Speech. Their `Title + 2 rows + dynamic columns + comments down` layout and `Dynamic Columns Field = Operator` create one column per selected Operator on the same slide, with LTE above NR and comments beneath. Every bin has one bar per Campaign, ordered oldest to newest: the newest uses the Operator colour and older Campaigns use progressively lighter shades. Percentages use the same valid-sample denominator and bin widths as the contour histograms.
- RSRP and SINR CDFs (LTE and NR) for Data, Voice and Speech, with contour histograms underneath in a two-by-two layout. RSRP uses 5 dB bins and SINR uses 1 dB bins; percentages are normalized per Operator and Campaign. Histograms reuse CDF colours and campaign line widths: newer campaigns are thicker, while multivendor operator comparisons retain their distinct line patterns;
- average LTE and NR RSRP and SINR bars per CDR type;
- separate LTE and NR RSRP distributions in -110/-100/-90/-80 dBm buckets and SINR distributions in 0/5/13/20 dB buckets, with red-to-green class colours matching the histogram background bands;
- separate LTE and NR shares of samples below -110 dBm and below 0 dB, calculated from valid measurements of each technology;
- LTE and NR coverage (RSRP) and quality (SINR) maps for Data, Voice and Speech, coloured from red to green using the same quality ranges; maps combine the measured samples in the selected Operator, Campaign and geographical filters, rather than estimating unmeasured coverage;
- the same black-logo closing slide as the NSA NetCheck template.

Edit, rename or delete them like any other template or Dashboard. A deleted copy is not recreated.

> [!IMPORTANT]
> NSA uses an LTE anchor and can also provide NR radio measurements. Each chart reads its technology-specific CDR field. NR percentages describe the available valid NR measurements; missing NR values do not count as good coverage or establish NR availability along the entire route. SINR reflects signal quality against both interference and noise.

## Data sources

| Field | CDR Data | CDR Voice (A side) | CDR Speech |
| --- | --- | --- | --- |
| LTE RSRP / SINR | `LTE_PCell_RSRP_Avg`, `LTE_PCell_SINR_Avg` | `4G_RSRP_Avg_A`, `4G_SINR_Avg_A` | `Playing_RSRP_Avg`, `Playing_SINR_Avg` |
| NR RSRP / SINR | `NR_PCell_RSRP_Avg`, `NR_PCell_SINR_Avg` | `NR_RSRP_Avg_A`, `NR_SINR_Avg_A` | `Playing_RSRP_NR_Avg`, `Playing_SINR_NR_Avg` |
| Location | `Test_Start_Latitude/Longitude` | `Call_Start_Latitude/Longitude_A` | `Playing_Latitude/Longitude` |
| Serving cells | `LAC_CID_xARFCN`, `Cell_ID` | `LAC_CID_xARFCN_A`, `Cell_ID_A` | `Cell_IDs_A`, `Playing_eNodeBId` |
| Bands | `LTE_PCC_EARFCN`, `NR_DL_PCell_Band` | `E/U/ARFCN_A`, `NR_BAND_A` | `ARFCN_A` |

Speech falls back to the `Recording_*` fields when the `Playing_*` fields are absent. Region and City use `Region`/`City`, or `G_Level_2`/`G_Level_4`.

## Pending inputs

| Input | Used by | How to provide it |
| --- | --- | --- |
| Site inventories for every Operator | Cluster Sites Density, Network Deployment | Upload them as Vendor mapping datasets (Vodafone and Three are supported today) |
| Cluster polygons | Cluster Sites Density | Upload GeoJSON, JSON or a zipped shapefile as Clusters — Geospatial in Workspace; density calculation remains pending |
| Licensed spectrum per Operator | Spectrum | [Workspace Config → Spectrum Holdings](workspace-config.md#spectrum-holdings) |
| NNS site list, if it differs from the inventory eMOCN Scenario | Network Deployment | Include it in the uploaded inventory |

## Persistence and transfers

Analyses are calculated on demand. Spectrum Holdings belong to the workspace and travel with the **Operator & Vendor Maps** export, transfers and backups. Workspace templates and Dashboards travel with Report Templates and Dashboards.

Network Insights remembers the selected CDRs, NR Mode, Technology, grouping, filters, thresholds, map grid and deployment grouping in this browser, separately for each workspace and user. Unavailable CDRs or values are omitted when restored. These browser preferences are not included in workspace exports or backups.

## Troubleshooting

- **No ready CDRs** in a CDR list: check the NR Mode and that the CDRs finished processing.
- **No samples match**: clear the Operator, Vendor, Region, City or Campaign restriction.
- **A map is empty**: the selected CDRs carry no coordinates or no values for the selected Technology; the status line says which.
- **NR curves are empty**: NSA CDRs report NR values only while the device is attached to NR; check the NR RSRP samples column in the RF Quality table.
- **The Licensed spectrum panel shows Pending input**: add Spectrum Holdings in Workspace Config.
