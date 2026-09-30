# Scoring & GAP Analysis

This workspace module calculates NetCheck KPI scoring and operator comparisons from processed Data, Voice and Speech CDRs. It uses the supplied 2026 Q2 City/Road scoring workbook, Tableau Prep flow and NetCheck methodology. Scoring jobs are independent of Dashboard and Report Templates.

## Calculate and review

1. Open the workspace, import its methodology under **Workspace Config → Scoring KPI Configuration** if it is not configured yet, and finish processing the required CDRs.
2. Open **Scoring & GAP Analysis** and select **NSA** or **SA**. A job cannot combine both modes.
3. The Data, Voice and Speech subpanels initially select the latest uploaded ready CDR of each type for the chosen NR Mode. Select at least one of each type in every included campaign; calculation is disabled until the complete selection is available. Choose the aggregation dimensions. **Operator** is always included; **Region**, **City**, **Vendor** and **Dataset Type** can be combined with it. Campaign remains a separate comparison dimension.
4. Choose the reference operator in the **GAP reference operator** dropdown populated from Operator Mapping. The default is **EE**, matching the supplied GAP presentation.
5. Optionally restrict **Regions**, **Cities**, **Operators**, **Vendors** and **Campaigns**. Their choices combine the cached values of all selected CDRs. **Main Cities** selects the configured workspace cities present in that selection, as in E2E Dashboards. Empty selections mean all values; values within one field are combined with OR, and different fields with AND. Filters apply before KPI calculation, independently of aggregation. Keep at least one Data, Voice and Speech CDR for every included campaign.
6. Click **Calculate Scoring**. An unchanged selection reuses its saved result or existing queued job. **Recalculate** forces a new calculation once any identical active job has finished.
7. Follow the persistent background job in **Scoring Jobs**, then inspect **Scoring Tables**, **GAP Analysis**, **Scoring Chart** and **Best Network Chart** in the full-width **Scoring Results** panel below it. Selecting an older job shows its original saved results and warnings.
8. Use the **Delete scoring job** action on a job to remove it and its saved results after confirmation. Source CDRs remain available. Queued work is skipped; running work stops at the next processing checkpoint or discards its pending result. The same selection can then be calculated again.

After a CDR finishes processing, the application queues its default Operator calculation when ready Data, Voice and Speech companions exist for its campaign and NR Mode. **Recalculate Scoring** in Workspace includes the selected CDR and the latest compatible companions of the other types, then opens the scoring module.

CDR processing caches Operator, Vendor, Region, City and Campaign values. Older catalogue rows are filled once using distinct-value queries; opening the module again and changing selections reuse the cache without rescanning the CDR rows.

Rows are pooled before KPI calculation within the same selected grouping. This avoids averaging previously calculated averages or percentiles from separate files. Campaigns remain separate even though the supplied Prep flow's final dataset key contains only Operator and the two environment fields.

## Results and workspace settings

The **Environment** dropdown applies to Scoring Tables, Scoring Charts and GAP Analysis. DriveCity and DriveConnectionroad show their own contributions. Combined is available only when both environments occur in the same comparison context; missing KPI values remain unavailable instead of being replaced with zero or renormalized.

Scoring Tables use one row per KPI, category blocks, weights and maximum points, followed by operator scoring columns and signed GAP columns. **Show KPI values** adds the measured values for each operator before the scoring columns, under a shared **KPI Value** header; the points columns share a **Score** header. A bright yellow horizontal line above the reference operator header marks the selected reference. Tables grow to show all rows without an internal vertical scrollbar. Operator Mapping supplies the operator labels, reference dropdown, column/series order and colors for the web views and PowerPoint; unmapped operators follow the configured operators alphabetically. Mapping updates apply when reopening saved results without changing their measured values.

Numeric scoring cells use Low, Medium, High and UltraHigh threshold colors; unavailable or incomplete measurements use neutral cells. GAP cells use a shared scale for each comparison context, with negative deficits becoming red and positive advantages green; a nonlinear intensity scale makes smaller differences visible. Legends explain the independent threshold and GAP scales. Scoring Chart shows all categories and operators together in one chart for the selected comparison context, with weighted points and numeric labels. Best Network Chart combines stacked Voice/Data points and a donut of their configured maximum allocation, following the reference presentation. Its maximum follows the selected environment and configured weights; missing inputs are not scaled to a full result. Both views support enlarged floating charts by double-click.

GAP Analysis initially selects **All vs reference**, displaying every compared operator in a single priority-ordered table. The highlighted **Operator comparison** dropdown also offers individual operators. Missing comparisons remain N/A, and total GAP requires complete coverage on both sides.

Under **Config → Workspace Config**, **Scoring KPI Configuration** sits above **GAP KPI Priority**. KPI settings customize the City/Road thresholds, maximum points (weights), KPI types and interpolation score anchors. Calculation formulas and filters follow the imported configuration and the operations supported by the engine. The priority panel orders the comparable KPI rows shown in GAP Analysis. Save settings before creating a new job. Jobs retain their calculation configuration, so changing settings changes the cache identity and new calculations while preserving historical jobs.

**Import JSON** and **Export JSON** use the same portable format as the configuration document in ZIP packages. Both settings travel together through the **Scoring Configuration** import/export component, workspace transfers and configuration backups/restores. Full workspace database backups also include them.

## Methodology

Scoring rules are read exclusively from the workspace database. The local, Git-ignored reference `assets/scoring/netcheck_2026.json` can be imported explicitly to initialize those rules. Its thresholds and weights come from `Netcheck_Score_Mapping_2026Q2_BestNetwork_Drive_City_Road.xlsx`; KPI definitions and filters come from `Join_NC_CDR_KPIsv3_all_UK.tfl`, with methodology context from `20260416 NET CHECK Press Benchmarking Package for Mobile Networks.pdf`.

The original documents are reference material, not application dependencies. The reference JSON contains extracted rules in the same format as exported Scoring Configuration documents; its document names and spreadsheet/Prep references are provenance only. It is never loaded automatically. [Scoring methodology configuration](scoring-methodology.md) describes every field, the runtime consumers and the update/migration procedure for a future NetCheck methodology.

- `G_Level_1 = Drive` and `G_Level_2 = City` select the City mapping. `Drive` and `Connectionroad` select the Road mapping. Geography fields do not substitute for these environment fields.
- KPI scores are piecewise linear between the workbook's threshold anchors and clipped to the allowed range. Low maps to 0%, Medium to 80%, and High to 100% for mappings without Ultra. With Ultra, the throughput P90 KPIs C25/C30 use High = 90%; the other supported mappings use High = 95%. Ultra maps to 100%. These per-KPI anchors follow the supplied workbook and can be changed in Workspace Config.
- Dynamic best-value Ultra thresholds use all operators in the selected comparison context, following the PDF's best-achieved definition. The current Excel City cells J23/J28/J29 instead use M:O and exclude 3/EE, without a documented reason; Road uses K:O. This deliberate generalization supports arbitrary operator selections and is not literal parity with those City spreadsheet ranges. Source formula references retain the actual ranges for audit.
- City and Road retain their prescribed 65%/35% contribution. Missing environments, CDR types, fields or valid samples do not cause the remaining points to be silently scaled to a full score.
- KPI rows retain values, normalized scores, weighted points, maximum points and sample counts. Charts show weighted score points and use the reference operator and configured Operator Mapping order/colors. Coverage warnings explain missing or unsupported inputs.
- GAP is **compared operator weighted points minus reference operator weighted points**, in the same units as the scoring table. A positive GAP means the operator has more points and is green; a negative GAP means it has fewer points and is red. Saved jobs from the earlier inverse convention are converted when read/exported without changing their stored measurements. Both sides must exist in the same comparison context; the module does not substitute the best operator when the baseline is absent.

The supplied mapping applies to Drive City and Drive Connectionroad. The NR selector separates dataset universes; it does not imply that another methodology has been provided for SA or for other environments. Historical jobs over a single CDR type remain readable with partial coverage. New calculations require Data, Voice and Speech inputs; complete benchmark results also require the applicable measurements and City/Road coverage.

The PDF's Drive/Walk allocation includes scopes outside this workbook and totals 675 points; it is not the workbook's 650/350 two-environment scale. The implementation keeps the supplied Excel's 1,000-point allocation instead of mixing both profiles.

The reference PPT contains an earlier Q4 Drive City weighting: Classic Call Success has a 142.80-point maximum, compared with 73.4825 City points in the supplied Q2 workbook (113.05 City plus Road). Its table layout applies here, but the supported GAP convention is operator minus reference, and its absolute points are not a numeric golden for this mapping version.

## Persistence and exports

The workspace SQLite **Scoring And GAP Analysis Jobs** table stores the selected CDR identifiers, source metadata, aggregation levels, selected scope filters, NR Mode, baseline, methodology version, job status and complete result. Filter selections participate in cache identity, regardless of selection order, and remain attached to historical jobs and their exports. Cache reuse checks the processed CDR metadata and supported dataset changes, including Database Management row edits. Old jobs remain historical snapshots after reprocessing.

- **Scoring CSV** and **GAP CSV** export every saved result row with UTF-8 column names and numeric values. When category/overall summaries accompany KPI details, `row_type` distinguishes `summary` from `kpi`. CSV export does not recalculate KPIs.
- **PowerPoint** exports the saved job using the configured `Template_CDR_analysis.pptx`. A **Scoring & GAP Analysis** cover and transition slide open the deck, showing the chosen filters/aggregation and campaign names in both opening slides. Files follow the E2E Dashboard naming format: `YYYYMMDD_HHMMSS - NR Mode - Scoring & GAP Analysis - Scope - Regions - Campaigns.pptx` (the campaign suffix compares multiple campaigns). Each comparison context then has **Best Network**, the single **Scoring Chart**, the **Scoring Table**, the combined **All vs reference GAP Analysis**, followed by signed **GAP Analysis** tables for each compared operator. Slide titles/subtitles identify the campaign, environment and aggregation context. Analysis slides use editable reference-style KPI matrices and prioritized signed GAP tables on white backgrounds, alongside charts with Operator Mapping colors and value labels. Best Network labels show both Voice/Data contributions and their total above each bar; the Scoring Chart legend sits above the plot. Pagination preserves every operator and KPI when needed. Coverage warnings are included in slide notes and incomplete values are marked.
- Workspace duplication, workspace database exports, transfers, ZIP backups and restores carry saved jobs and results with the SQLite database. Configuration-only or template-only packages exclude these CDR-dependent results; use CSV/PPT for standalone result sharing.
- Interrupted queued/running jobs are retained as failed jobs when recovered after restart. Recalculate to create a fresh attempt; completed results remain readable.
- Existing workspace job tables using the earlier `ready` status are migrated to `completed` when the workspace is initialized, preserving job identifiers and saved results.

## Troubleshooting

- No CDR is selectable: verify the active workspace, NR Mode and processing status.
- A geographic or vendor grouping is unavailable: populate or map the corresponding source field first. Environment labels such as City/Road are not Region values.
- No GAP appears: verify that the chosen baseline has valid measurements in the same campaign, environment and geographic/vendor context as the compared operator.
- A job reports that its CDR changed: wait for processing or mapping to finish, then calculate again.
- A saved job reports a status CHECK constraint error: restart the application to apply the workspace schema migration, then recalculate. Failed attempts remain available for review or deletion.
- Results differ from another campaign's report: check the mapping version, filters, environment coverage, included operators and dynamic best-value thresholds.

## Supported KPI allocation

The table lists the fixed maximum ranking points for each environment. Ratio calculations count non-null denominator fields after the Prep filters. The POLQA low-quality condition is `LQ <= 1.6` despite the source label; Call Setup Time uses `> 10 s` from Prep/Excel, while the older example PPT labels that threshold `> 15 s`.

| Code | Category | KPI | City points | Road points |
|---|---|---|---:|---:|
| C5 | CLASSIC CALLS | CALL SUCCESS RATIO [%] | 73.4825 | 39.5675 |
| C6 | CLASSIC CALLS | CALL SETUP TIME [s] | 8.6450 | 4.6550 |
| C7 | CLASSIC CALLS | CALL SETUP TIME > 10 s [%] | 4.3225 | 2.3275 |
| C8 | CLASSIC CALLS | POLQA < 1.6 [%] | 22.7500 | 12.2500 |
| C9 | CLASSIC CALLS | POLQA [MOS | 7.5855 | 4.0845 |
| C10 | CLASSIC CALLS | DISTURBED & IMPAIRED CALL [%] | 15.1645 | 8.1655 |
| C11 | WHATSAPP CALLS | CALL SUCCESS RATIO [%] | 56.8750 | 30.6250 |
| C12 | WHATSAPP CALLS | POLQA < 1.6 [%] | 14.7875 | 7.9625 |
| C13 | WHATSAPP CALLS | POLQA [MOS] | 4.9270 | 2.6530 |
| C14 | WHATSAPP CALLS | DISTURBED & IMPAIRED CALL [%] | 9.8605 | 5.3095 |
| C15 | MULTI RAB | MULTI RAB DATA TRANSFER SUCCESS RATIO [%] | 9.1000 | 4.9000 |
| C17 | TRANSFER | FDFS DL SUCCESS RATIO [%] | 30.4200 | 16.3800 |
| C18 | TRANSFER | FDFS DL TRANSFER TIME [s] | 20.2800 | 10.9200 |
| C19 | TRANSFER | FDFS UL SUCCESS RATIO [%] | 15.2100 | 8.1900 |
| C20 | TRANSFER | FDFS UL TRANSFER TIME [s] | 10.1400 | 5.4600 |
| C21 | TRANSFER | FDTT DL THROUGHPUT > 2Mbit/s [%] | 20.2800 | 10.9200 |
| C22 | TRANSFER | FDTT DL THROUGHPUT > 5Mbit/s [%] | 25.3500 | 13.6500 |
| C23 | TRANSFER | FDTT DL THROUGHPUT > 20Mbit/s [%] | 25.3500 | 13.6500 |
| C24 | TRANSFER | FDTT DL THROUGHPUT > 100Mbit/s [%] | 15.2100 | 8.1900 |
| C25 | TRANSFER | FDTT DL THROUGHPUT P90 [Mbit/s] | 15.2100 | 8.1900 |
| C26 | TRANSFER | FDTT UL THROUGHPUT > 1Mbit/s [%] | 10.1400 | 5.4600 |
| C27 | TRANSFER | FDTT UL THROUGHPUT > 3Mbit/s [%] | 12.6750 | 6.8250 |
| C28 | TRANSFER | FDTT UL THROUGHPUT > 10Mbit/s [%] | 12.6750 | 6.8250 |
| C29 | TRANSFER | FDTT UL THROUGHPUT > 20Mbit/s [%] | 7.6050 | 4.0950 |
| C30 | TRANSFER | FDTT UL THROUGHPUT P90 [Mbit/s] | 7.6050 | 4.0950 |
| C31 | HTTP/HTTPS BROWSING | BROWSING TIME TO 1MB [ms] | 33.8000 | 18.2000 |
| C32 | HTTP/HTTPS BROWSING | BROWSING SUCCESS RATIO [%] | 50.7000 | 27.3000 |
| C33 | VIDEO STREAM | VIDEO STREAMING SUCCESS RATIO [%] | 54.0800 | 29.1200 |
| C34 | VIDEO STREAM | VIDEO STREAMING TTFP >= 10 s [%] | 3.3800 | 1.8200 |
| C35 | VIDEO STREAM | VIDEO STREAMING IRRITATING EXPERIENCE [%] | 27.0400 | 14.5600 |
| C36 | INTERACTIVITY | INTERACTIVITY PACKET ERROR RATIO [%] | 5.0700 | 2.7300 |
| C37 | INTERACTIVITY | INTERACTIVITY MEDIAN RTT [MS] | 20.2800 | 10.9200 |
