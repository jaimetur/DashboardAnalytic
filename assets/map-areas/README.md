# Map Areas shipped with the application

The Points Lost Map of Scoring & GAP Analysis colours the administrative areas of each country of the tests. These layers are shipped so that a workspace (also on a server without Internet access) has them without downloading anything; a workspace can replace any of them with its own in Workspace Config → Map Areas. A country with no layer, shipped or of the workspace, is coloured as one area, the whole country.

Each `<ISO3>.json.gz` holds the simplified polygons of one country (coordinates rounded to four decimals); `manifest.json` lists them. For each country other than the United Kingdom, the level whose mean area is closest to that of the UK ITL3 areas (about 1,340 km²) was chosen. Polygons with the same name in the same region are the parts of one area, and a name found in several regions carries the name of the region (for example *Washington (Ohio)*).

| Country | Level | Areas | Source | Licence |
| --- | --- | --- | --- | --- |
| Canada (CAN) | census subdivision (ADM3) | 5031 | Statistics Canada (StatCan) | Open Data Commons Open Database License 1.0 |
| France (FRA) | arrondissement (ADM3) | 320 | Institut national de l'information géographique et forestière (IGN-F) | Etalab Open License 2.0 |
| Germany (DEU) | independent city or district (ADM3) | 401 | Federal Agency for Cartography and Geodesy | Data license Germany - Attribution - Version 2.0 |
| India (IND) | district (ADM2) | 735 | Pathways Data Pvt. Ltd., lgdirectory.gov.in | Open Data Commons Open Database License 1.0 |
| Italy (ITA) | province (ADM3) | 107 | ISTAT, National Institute of Statistics | Creative Commons Attribution 3.0 License |
| Japan (JPN) | prefecture (ADM1) | 47 | OpenStreetMap, Wambacher | Open Data Commons Open Database License 1.0 |
| Mexico (MEX) | municipio (ADM2) | 2457 | World Bank | Creative Commons Attribution 4.0 (CC BY 4.0) |
| Netherlands (NLD) | province (ADM1) | 12 | National Georegister | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication |
| Poland (POL) | county (ADM2) | 380 | Geoboundaries, OpenStreetMap | Open Data Commons Open Database License 1.0 |
| Portugal (PRT) | district (ADM1) | 20 | DG Territory | Open Data Commons Open Database License 1.0 |
| Romania (ROU) | county (ADM1) | 42 | World Bank | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| South Korea (KOR) | district (ADM2) | 228 | geoBoundaries, citypopulation.de | Creative Commons Attribution 3.0 License |
| Spain (ESP) | province (ADM2) | 52 | El Instituto Nacional de Estadística | National Institute of Statistics (INE) Data License |
| Switzerland (CHE) | canton (ADM1) | 26 | Federal Office of Topography swisstopo | Federal Office of Topography swisstopo License |
| United Kingdom (GBR) | ITL3 area (ITL3) | 182 | Office for National Statistics | Open Government Licence v3.0 |
| United States of America (USA) | county (ADM2) | 3227 | United States Census Bureau, MAF/TIGER Database | Public Domain |

- **United Kingdom:** Office for National Statistics, *International Territorial Level 3 (January 2025) Boundaries UK BUC (V2)*, ONS Open Geography Portal (the UK NUTS3 level). Contains OS data © Crown copyright and database right 2025.
- **Other countries:** geoBoundaries (William & Mary geoLab), www.geoboundaries.org, gbOpen release, from the national sources above. Use them under the licence of each country.

## World countries

`world-countries-50m.geojson.gz` holds the country polygons that find the country of each test (Map Areas of Workspace Config), draw the outline of the countries under their areas and colour a country without Map Areas as a whole. Only the ISO 3166 alpha-3 `code` and the English `name` are kept, geometries are simplified and coordinates rounded to three decimals.

Source: Natural Earth, *Admin 0 – Countries* (1:50m), naturalearthdata.com. Licence: public domain.
