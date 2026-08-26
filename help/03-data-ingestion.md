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

## Reporting inputs

NetCheck Data, Voice and Speech CDRs are classified automatically and stored in SQLite after processing. Reporting uses those persisted rows; users do not upload the same CDR a second time when generating a report.

A file whose name contains `Mapping` is classified as `Multivendor Mapping`. Upload one mapping for Vodafone and a separate mapping for Three before creating a multivendor report. Each file must expose a Global CI/Cell ID field and a Vendor field (for example, `Cell ID` and `OP/ Vendor`).
