# PowerPoint Reporting

The application supports two PowerPoint paths:

- **Dashboard export** generates a generic PowerPoint from the currently selected interactive dashboard state.
- **E2E Bench Reporting → NetCheck CDR Reports** generates an NSA or SA CDR report from the supplied NetCheck templates.

## NetCheck CDR report

Select one processed `CDR-Data`, `CDR-Voice` and `CDR-Speech` dataset, then select NSA or SA. The report filters sessions using `ENDC` for NSA and `NR` for SA in `RAT`, `RAT_A` or `Sample_RAT_A`.

For multivendor output, select a processed `Multivendor Mapping` dataset. Vodafone and Three series are derived from the first and last Global CI of the session using the agreed business formula. The report uses the template layout from `assets/templates/`, retains scoring and gap slides without automation, clears analyst-comment text boxes, and inserts computed CDR charts in the automated analysis slides.

Template location can be overridden at deployment time with `APP_REPORTING_TEMPLATE_DIR`.
