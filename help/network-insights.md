# Network Insights

Analyse the network behind the measured performance: radio quality (RSRP and SINR), weak-coverage and high-interference areas on a map, observed and inventoried sites, licensed and observed spectrum, and network deployment (NNS, eMOCN scenarios, host networks and RAN vendors). The **Filters:** section offers Operators, Vendors, Regions, Cities and Campaigns. **Main Cities** appears first in the Cities menu when configured in the workspace; selecting it applies the configured cities available in the selected CDRs. Values load automatically from the lightweight CDR catalogues without waiting for a full analysis. The selectors show **Loading values…** while the request is pending. The persistent CDR catalogue stores both Vendor and Vendor_Only universes. Vendor choices are read exclusively from the Vendor_Only cache, populated during CDR processing. Existing CDRs receive a one-time backfill when this cache is first requested. Vendor loading runs separately, so its initial lookup does not hold up Operators, Regions, Cities or Campaigns. These four filters use cached CDR catalogues; legacy CDRs need their catalogues populated during CDR processing.

Measured views group only by the checked **Group by** dimensions: Campaign, Operator, Vendor, Region, City and CDR type. Multiple checked dimensions form a hierarchy in selector order. Campaign is always the last grouping dimension, including when Technology is available. Measured tables use alphabetical order by the selected hierarchy, keeping each operator/group and its technologies/campaigns together. The map Group selector follows the displayed table rows exactly, rather than the source CDR or campaign order. Operator is included only when checked; otherwise samples from selected operators sharing the other dimensions are combined. With no dimensions checked, the view pools all selected samples. Licensed spectrum and uploaded inventories retain their own reference dimensions.

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
2. Choose **NR Mode**. The CDR lists show the ready Data, Voice and Speech CDRs of that mode; the two most recently uploaded CDRs of each type are selected.
3. Choose **Technology** (LTE, NR or LTE+NR) and **Group by** (Campaign, Operator, Vendor, Region, City or CDR type).
   **Group by** is a multiple selection: choose one or more dimensions. **Operator** separates operators only when checked. **Vendor** splits each operator by vendor, using only `Vendor_Only`. The Vendors filter also uses only this field. Actual vendors appear first, followed by Mixed Vendor(s), Other Vendor(s), All Vendor(s), and then operator-only identities labelled **Operator - All Vendors**; labels do not change the stored filter values. CDRs without it contribute no vendor choices.
4. Adjust **Low coverage below** (default -110 dBm), **High interference below** (default 0 dB) and the **Map grid** size (default 250 m).
5. Press **Analyse Network**.

After the first analysis, **Operators**, **Regions** and **Cities** list the values found in the selected CDRs. Restrict them and press **Analyse Network** again. Leaving every value selected applies no restriction.

> [!TIP]
> The first analysis of a CDR copies its radio fields into the combined reporting tables and can take a minute. Later analyses of the same CDRs reuse them and the parsed samples, so changing filters, thresholds or the map Operator is fast.

Operator names follow the workspace **Operator Maps**, including their colours; rows from ignored CDR sheets are excluded.

## Overview and RF Quality

The **Overview** shows one card per Operator with the median RSRP, the share of samples below the coverage threshold, the median SINR, the share of samples below the interference threshold, the observed eNodeBs and the number of samples. When the selection contains two or more campaigns, each indicator shows its change between the two latest campaigns: green when the indicator improves and red when it worsens.

**RF Quality** contains:

- the RSRP and SINR cumulative distributions, one curve per Operator; grouped analyses use a different line style per group;
- a table per Operator and group with median and 10th-percentile RSRP and SINR, the low-coverage and high-interference shares and the quality-class distribution.

| Class | RSRP (dBm) | SINR (dB) |
| --- | --- | --- |
| Excellent | ≥ -80 | ≥ 20 |
| Good | -90 to -80 | 13 to 20 |
| Fair | -100 to -90 | 5 to 13 |
| Poor | -110 to -100 | 0 to 5 |
| Very poor / Bad | < -110 | < 0 |

Values outside physical ranges (RSRP outside -160 to -20 dBm, SINR outside -30 to 50 dB) are treated as missing.

## Coverage and Interference Maps

The maps show one Operator at a time over OpenStreetMap. Samples are grouped into square grid cells of the selected size, and each cell is coloured by its mean RSRP or SINR class. Cells need at least three located samples. Very dense selections use a coarser grid automatically to keep the map readable; the note above the maps shows the grid actually used.

Below each map, the **Weakest coverage areas** and **Highest interference areas** tables rank the cells where at least half of the samples are below the threshold, by the number of affected samples. Select an area (its City) to zoom the map to it, and **Show Whole Area** to return. Drag a rectangle over a map to magnify it, then drag to pan.

## Sites and Density

The table counts, per Operator and group, the **observed eNodeBs** (distinct LTE eNodeB identities, Cell Identity ÷ 256, that served the measuring devices) and **observed cells**, with the samples per eNodeB. Observed eNodeBs depend on the route and do not equal the deployed sites.

When a Vodafone or Three cell inventory is uploaded as a Vendor mapping dataset in Workspace, the panel also shows its total number of distinct sites and cells.

## Spectrum

**Licensed spectrum** aggregates the MHz configured in [Workspace Config → Spectrum Holdings](workspace-config.md#spectrum-holdings) per Operator into Low (below 1 GHz), Mid (1–3 GHz FDD/SDL) and High (TDD) bands. Without holdings, the panel shows a pending-input notice.

**Spectrum observed in the measurements** shows the share of samples served on each LTE band (from the serving EARFCN or the band of the cell trace) and NR band, with the frequency, duplex mode, class and the most frequent downlink bandwidth. Bandwidths are reported only by CDR Data.

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

Network Insights stores no analysis results; every analysis is calculated on demand. Spectrum Holdings belong to the workspace and travel with the **Operator & Vendor Maps** export, transfers and backups. Workspace templates and Dashboards travel with Report Templates and Dashboards.

## Troubleshooting

- **No ready CDRs** in a CDR list: check the NR Mode and that the CDRs finished processing.
- **No samples match**: clear the Operator, Region or City restriction.
- **A map is empty**: the selected CDRs carry no coordinates or no values for the selected Technology; the status line says which.
- **NR curves are empty**: NSA CDRs report NR values only while the device is attached to NR; check the NR RSRP samples column in the RF Quality table.
- **The Licensed spectrum panel shows Pending input**: add Spectrum Holdings in Workspace Config.

> [!NOTE]
> **Vendor comparison:** Before generating a multivendor report, choose **Operator – Vendor** to keep each operator separate, or **Vendor only (Vendor_Only)** to pool selected operators using the same vendor. Campaigns remain separate. The job retains this choice for retries. Dynamic vendor grids use up to six columns per slide and keep operators of the same vendor together where possible.

### LTE+NR selection

**LTE+NR** shows LTE and NR CDF curves together, labelled by technology (NR uses dashed lines). Summary statistics and map grids pool valid radio measurements from both technologies; source sample and observed-site counts remain unduplicated. A source row can contain both an LTE and an NR measurement, so the RSRP/SINR measurement counts can exceed source sample counts. Select LTE or NR for technology-specific statistics and maps.

The Overview, RF quality tables/CDFs, observed sites, observed spectrum and map group picker use the selected hierarchy. Site identifiers are scoped by source operator before counting pooled groups. Changes between the latest two campaigns are shown only when Campaign is not itself a grouping dimension.

### Remembering selections

Network Insights remembers the selected CDRs, NR Mode, Technology, grouping levels, filters, thresholds, map grid and deployment grouping in this browser, separately for each workspace and user. Reloading restores valid selections; removed CDRs or unavailable values are omitted. Analysis results are not stored by this preference: press **Analyse Network** to recalculate them. Browser selections are local preferences and are not included in workspace exports or backups.

When **Technology** is **LTE+NR**, **Group by** also offers **Technology**. Checking it separates LTE and NR in the selected hierarchy for summaries, tables, charts and maps. The option is removed for LTE-only or NR-only analysis. A source row with measurements from both technologies contributes once to each technology group.

Filters appear above the CDR dataset groups. By default, all ready CDRs of the selected NR Mode are checked. Your saved dataset selection takes precedence after you change it.

Network Deployment reuses a narrow inventory projection and grouped counts while the inventory revision remains unchanged. Changing Group by discards older pending responses; processing or editing an inventory invalidates its cached counts. A timed-out request shows an error instead of remaining on the loading message.
