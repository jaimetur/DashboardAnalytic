# Query Builder

Query Builder runs read-only SQL against selected, processed Data, Voice and Speech CDRs in the active workspace. Use **Assistance Mode** to assemble common queries with form controls, or **SQL Mode** to edit SQL directly.

## Assistance Mode

1. Open **Query Builder** with a workspace active.
2. Select one or more ready source datasets and one or more **CDR types to use** represented by those sources.
3. By default, **Show all fields** is off and `source_dataset_name` and `cdr_type` are preselected. Enable **Show all fields** to include every available column, or choose the fields to include in the result.
4. Add filter conditions by choosing a column, comparison and value. Choose **AND** or **OR** between conditions to control how they are combined.
5. Choose the sort order and maximum rows, or select **All rows** to omit the SQL `LIMIT`.
6. Review the generated SQL, then run the query.

Use **Clear Query** to start over. After you confirm, it clears the SQL, source selections, filters, field selection, sorting, limit and current results. Cancel keeps the current query unchanged; saved queries are not deleted.

The SQL preview updates live as you change the controls; the results table updates only after **Run query**. An incomplete filter does not erase the SQL preview: completed filters and other valid selections continue to appear, and the assistant explains what needs attention. At least one CDR type must remain selected; if you try to clear the last one, it is restored and the assistant explains why. If no source or output field is available, the preview displays what is needed to continue. **Run query**, **Save query** and **Export CSV** are disabled until the query has a valid selection and every filter is complete.

The result panel reports the current page's row count and columns, plus the total number of matching rows. Results are paginated in batches of up to 50 rows. Navigation controls above and below the table let you jump to the first or last page, or move to the previous or next page. With **All rows**, the generated SQL has no row limit and the pages cover all matching rows. Use the filter button in a result column's header to search its distinct values, select the values to keep, and apply or clear the filter. The menu shows up to 200 values at a time; search to find additional values. Filters in different columns combine and apply to the full query result, including later pages. They reset when you run a new query. **Copy** copies the column headers and rows on the visible filtered page as tab-separated text. **Export CSV** downloads all rows and columns in the filtered result, without a row cap.

For a `source_dataset_name` filter using **Is** or **Is not**, choose a name from the selected source datasets that match the selected CDR types. Other comparisons use a text value.

When multiple CDR types are selected, Assistance Mode combines their results with `UNION ALL` and includes a `cdr_type` column to identify each row's source type. Each type contributes its own `SELECT` against the corresponding temporary view (`selected_data`, `selected_voice` or `selected_speech`); selected output fields remain aligned across the combined results, with unavailable fields returned as `NULL`. Filters apply to the combined results. Choose **AND** or **OR** for each condition after the first; mixed connectors are evaluated from top to bottom and grouped with parentheses.

Assistance Mode shows the generated SQL in a read-only preview. You can switch to **SQL Mode** and back while the preview still contains its initial guidance. Switch to **SQL Mode** to adjust the statement or create joins, common table expressions, aggregates or other SQL that the guided controls do not represent. When loading a saved query, SQL that matches the Assistance Mode controls is restored in **Assistance Mode**; custom or unsupported SQL remains in **SQL Mode**.

## SQL Mode

Enter manual SQL in the **SQL Query** editor. Queries may use the temporary views `selected_data`, `selected_voice` and `selected_speech` for the selected source datasets. Each view includes original source columns plus `source_dataset_id`, `source_dataset_name` and `source_row_id`. A query must be a single read-only `SELECT` statement, optionally beginning with `WITH`.

SQL Mode follows the same 50-row pages, total result count, navigation above and below the table, **Copy** and CSV export behavior. Select at least one ready source dataset before running or saving a query.

Runs and page changes continue in the background while Query Builder checks their status, so a long query does not need to hold one HTTP request open. Use **Cancel** in the running dialog to stop the current query. Only one Query Builder run can be active at a time across the server.

## Saved queries

- Give the query a name and optional description to save it in the active workspace database. Query Builder loads the saved library from that database and does not automatically recreate removed or built-in examples.
- Saving checks the SQL and selected source columns without executing the full query. Run it separately to inspect results.
- Loading a saved query restores its SQL and source selections. Generated SQL that matches the Assistance Mode controls also restores those controls; custom or unsupported SQL remains in **SQL Mode**.
- Saved queries retain SQL and source references, so queries saved before Assistance Mode remain available in the same editor.
- Use the delete button in the Saved queries library to remove a query after confirmation. The library and load picker refresh after deletion.
- Export an individual saved query as JSON for inspection or archiving. Use a Query Builder Queries package or workspace backup/export ZIP to import saved queries into another workspace.
- Workspace query packages match source datasets by file name, or by source file content and CDR type when names differ. A transfer reports unmatched or ambiguous sources instead of saving a query with missing selections. SQL conditions that inspect `source_dataset_name` still use the destination's file name, so review them after renaming a dataset.
