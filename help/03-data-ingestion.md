# Data Ingestion

The MVP accepts:

- `.csv`
- `.xlsx`
- `.xls`

The ingestion layer loads the file into a pandas DataFrame and derives:

- available columns
- numeric columns
- categorical columns
- row count

This metadata is later used by the analytics layer.
