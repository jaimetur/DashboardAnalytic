# Network Insights

Analyse the network behind the measured performance: radio quality (RSRP and SINR), weak-coverage and high-interference areas on a map, observed and inventoried sites, licensed and observed spectrum, and network deployment (NNS, eMOCN scenarios, host networks and RAN vendors). Results are grouped by the dimensions checked in **Group by**; Operator and Campaign are checked by default.

> [!NOTE]
> **Radio views need no extra input.** RSRP, SINR, maps, observed eNodeBs and observed bands come from the processed CDRs. Site inventories and licensed spectrum are optional inputs that complete the Sites & Density, Spectrum and Network Deployment panels.

## Choose your task

| I want to… | Go to |
| --- | --- |
| Run an analysis | [Analysis Selection](#analysis-selection) |
| Compare coverage and interference per Operator | [Overview and RF Quality](#overview-and-rf-quality) |
| Locate weak-coverage or high-interference areas | [Coverage and Interference Maps](#coverage-and-interference-maps) |
| Count sites and eNodeBs | [Sites and Density](#sites-and-density) |
| Compare Low, Mid and High (TDD) spectrum | [Spectrum](#spectrum) |
| Count NNS, eMOCN or shared sites | [Network Deployment](#network-deployment) |
| Present RSRP and SINR slides in a Dashboard | [RF Quality template and Dashboard](#rf-quality-template-and-dashboard) |
| Check which CDR fields are used | [Data sources](#data-sources) |
| Know which inputs are still missing | [Pending inputs](#pending-inputs) |

## Analysis Selection

1. Open the workspace and the **Network Insights** tab, which follows **Scoring & GAP Analysis**.
2. Choose **NR Mode**. All ready Data, Voice and Speech CDRs of that mode are selected; clear the ones you do not need.
3. Restrict **Operators**, **Vendors**, **Regions**, **Cities** or **Campaigns** in **Filters:** if needed. Their values load automatically from the selected CDRs; **Main Cities** appears first in Cities when configured. Leaving every value selected applies no restriction.
4. Choose **Technology** (LTE, NR or LTE+NR) and **Group by** (Operator, Vendor, Region, City, CDR type and Campaign).
5. Adjust **Low coverage below** (default -110 dBm), **High interference below** (default 0 dB) and the **Map grid** size (default 250 m).
6. Press **Analyse Network**.

### Grouping

**Group by** accepts several dimensions; they form a hierarchy in the selector order, with Campaign last. Each Overview card, table row, CDF curve and map group is one combination, for example `EE · 2026-Q2`.

- **Operator** is always checked unless **Vendor** is checked. With Vendor checked, uncheck Operator to pool the selected operators by vendor, or keep it to split each operator by vendor.
- **Vendor** uses `Vendor_Only`: actual vendors, then Mixed, Other and All Vendor(s), then operators without a mapped vendor as **Operator - All**.
- Curves of the same Operator share its colour and use a different line style for each Campaign or other secondary group.
- The change between the two latest campaigns appears only when Campaign is not a grouping dimension.
- eNodeBs and cells are counted per source operator, also when operators are pooled.

### LTE+NR

**LTE+NR** always adds **Technology** to the grouping, so LTE and NR results appear side by side and are never pooled: LTE RSRP/SINR and NR SS-RSRP/SS-SINR use different reference signals. A sample with both measurements contributes once to each technology. Select LTE or NR to analyse one technology.

> [!TIP]
> The first analysis of a CDR copies its radio fields into the combined reporting tables and can take a minute. Later analyses of the same CDRs reuse them and the parsed samples, so changing filters, thresholds or the map Operator is fast.

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

## Coverage and Interference Maps

The maps show one group at a time (selected in **Group**) over OpenStreetMap. Samples are grouped into square grid cells of the selected size, and each cell is coloured by its mean RSRP or SINR class. Cells need at least three located samples. Very dense selections use a coarser grid automatically to keep the map readable; the note above the maps shows the grid actually used.

Below each map, the **Weakest coverage areas** and **Highest interference areas** tables rank the cells where at least half of the samples are below the threshold, by the number of affected samples. Select an area (its City) to zoom the map to it, and **Show Whole Area** to return. Drag a rectangle over a map to magnify it, then drag to pan.

## Sites and Density

The table counts, per group, the **observed eNodeBs** (distinct LTE eNodeB identities, Cell Identity ÷ 256, that served the measuring devices) and **observed cells**, with the samples per eNodeB. Observed eNodeBs depend on the route and do not equal the deployed sites.

When a Vodafone or Three cell inventory is uploaded as a Vendor mapping dataset in Workspace, the panel also shows its total number of distinct sites and cells.

## Spectrum

**Licensed spectrum** aggregates the MHz configured in [Workspace Config → Spectrum Holdings](workspace-config.md#spectrum-holdings) per Operator into Low (below 1 GHz), Mid (1–3 GHz FDD/SDL) and High (TDD) bands. Without holdings, the panel shows a pending-input notice.

**Spectrum observed in the measurements** shows the share of samples served on each LTE band (from the serving EARFCN or the band of the cell trace) and NR band, with the frequency, duplex mode, class and the most frequent downlink bandwidth. Bandwidths are reported only by CDR Data. Observed bands follow the grouping: keep Operator checked to see each operator's own bands.

## Network Deployment

This panel reads the cell inventories uploaded as **Vendor mapping** datasets (Vodafone and Three) and counts distinct sites and cells grouped by eMOCN Scenario (for example S0, S1, NNS or S2), Host Network, Network, RAN Vendor, Region, Subregion, Site Type or Band. An inventory without the selected column shows its totals instead.

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
| Site inventories for every Operator | Sites & Density, Network Deployment | Upload them as Vendor mapping datasets (Vodafone and Three are supported today) |
| Surface of each Region and City | Site density per km² | Not yet configurable |
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
