# Web interface

The UI uses a shared header, module tabs, panels, dialogs and tables. Read [Product Overview](01-overview.md) for the purpose of each module.

## Navigation

Primary tabs:

- Workspace
- E2E Dashboard
- E2E Reporting
- Chart Builder

Utility tabs:

- Readme
- Changelog
- Help
- App Logs
- Admin, when authorised

Readme opens by default after login. Dashboard, Reporting and Chart Builder require an open workspace.

## Header controls

- Click the active-workspace badge to switch workspace.
- The workspace-size badge is recalculated after dataset, report and Chart Set operations.
- Click the username badge to change the current password.
- Use Logout to end the session.

## Panels

- A panel heading explains its purpose.
- Collapsible panels remember their open/closed state where supported.
- Status pills distinguish ready, processing, failed and stopped work.
- Destructive actions use red styling and request confirmation when appropriate.

## Searchable selectors

Single-select and multi-select controls share a compact searchable style.

- Type in the search field to narrow values.
- Multi-select controls preserve the order in which values are selected when order has meaning.
- **Select all / none** toggles the currently available options.
- Open menus are layered above their active dialog and positioned against their field.

## Filter Builder

The shared Filter Builder is used by Chart Builder, E2E Reporting Chart Preview and Slides Template Chart Preview.

- The field selector is searchable.
- Operators adapt to list, text and numeric conditions.
- Add or remove conditions without editing raw syntax.
- The parsed filter appears beneath the builder.
- `IN`/`NOT IN` lists may be typed without parentheses; the parser adds them.

## Tables

- Wide desktop tables use fixed action areas where needed.
- Database and filtered-dataset tables paginate on the server.
- Excel-style header menus search distinct values from the complete filtered source.
- Horizontal/vertical scrolling stays inside the table viewport when controls must remain visible.

## Dialogs and progress

Long operations use progress dialogs for stages such as:

- preparing an export;
- transmitting or receiving a server transfer;
- processing an import;
- loading a Chart Data Preview;
- loading a filtered dataset.

Blocking destination-transfer dialogs are restored after a browser reload while the accepted operation remains active.

## Small screens

The interface targets compact screens around the iPhone 13 base viewport (`390 × 844`).

- Panels use reduced side margins.
- Forms and action bars stack vertically.
- Dataset Management changes to a readable card-like table layout.
- Chart navigation appears below the chart and before Interactive Preview.
- Wide tables scroll inside their own containers rather than widening the page.
- Workspace Management remains visible when expanded.

On a phone, use portrait orientation for forms and landscape orientation when inspecting a very wide data table.
