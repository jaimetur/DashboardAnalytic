# Operators by country

`operators-by-country.json` lists, for the 50 main countries (ISO 3166 alpha-3 codes, in alphabetical order of their names), their mobile operators. A workspace created for one of these countries starts with these Operator Maps; a workspace created without a country starts without Operator Maps.

Each operator has:

- `canonical`: the label shown in every filter, table, chart, legend and report;
- `color`: the main colour of its brand, as `#RRGGBB` (an approximation of the corporate colour, to be adjusted in Workspace Config → Operator Maps when needed);
- `aliases`: the ways the CDRs write it, also followed by the country (`O2 DE`, or `O2 - de` as NetCheck writes it).

The United Kingdom keeps the labels and spellings of the NetCheck UK CDRs (EE, 3, VF, VF SA, VF VoNR, O2 and Lebara).
