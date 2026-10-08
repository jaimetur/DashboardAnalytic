# Geographic boundaries

`uk-itl3-2025.geojson` holds the 182 UK International Territorial Level 3 areas (the UK NUTS3 level) used by the Scoring & GAP Analysis **Points Lost Map**. Only the `ITL325CD` and `ITL325NM` attributes are kept and coordinates are rounded to four decimals (WGS 84).

Source: Office for National Statistics, *International Territorial Level 3 (January 2025) Boundaries UK BUC (V2)*, ONS Open Geography Portal.
Licence: Open Government Licence v3.0. Contains OS data © Crown copyright and database right 2025.

`world-countries-50m.geojson` holds the country polygons used to find the country of each test (Map Areas of Workspace Config) and to draw the outline of the countries under their areas. Only the ISO 3166 alpha-3 `code` and the English `name` are kept, geometries are simplified and coordinates rounded to three decimals.

Source: Natural Earth, *Admin 0 – Countries* (1:50m), naturalearthdata.com. Licence: public domain.

The administrative areas of other countries are not bundled: each workspace downloads them from geoBoundaries (www.geoboundaries.org, licence of each country and level shown before downloading) or imports them.
