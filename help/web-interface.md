# Web Interfaces

The UI uses a shared header, module tabs, panels, dialogs and tables. Read [Product Overview](overview.md) for the purpose of each module.

## Navigation

Primary tabs:

- Workspace
- Datasets Analysis
- E2E Dashboards
- E2E Reporting
- Builders (dropdown with Chart Builder and Query Builder)

Other tabs:

- Help
- App Logs
- Config (dropdown with Application Config and Workspace Config), for `user-editor`, `admin` and `super-admin` roles
- Admin, for `admin` and `super-admin` roles

Help Home opens by default after login. Dashboard, Reporting, Chart Builder and Query Builder require an open workspace.

Open **Builders** to choose **Chart Builder** or **Query Builder**. The Modules sidebar links to each builder directly. Within its Administrative Modules group, Application Logs is first and Administrator Config is last. The top tab for Administrator Config remains **Admin**.

Move the pointer near a viewport edge to reveal a collapsed Modules, Sections, Navigation or Releases tab. An invisible hover area beside each tab responds even while background tasks are running; task cards leave that edge clear. The tabs recede when the pointer leaves, and keyboard focus also reveals them. Modules uses nearly the full viewport height when needed and scrolls if the window is too short for every entry. In Help, Sections lists the current document's headings.

Open **Config** and choose **Application Config** for application-wide runtime settings or **Workspace Config** for Report Templates Management, Operator Mappings, Vendor Mappings and Main Cities in the active workspace. Workspace Config's Page Sections navigator jumps between the panels.

Help Navigation lists unnumbered documents under General, Main Modules, Administrative Modules and Reference. Docker Deployment follows Deployment Configuration in General. App Logs is the first administrative document and Administrator Config is the last. Readme and Changelog open Reference before Project Structure and Roadmap. The Help Home link stays above the groups. Documents outside a user's access are omitted.

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

The shared Filter Builder is used by Chart Builder, E2E Reporting Chart Preview and Report Template Chart Preview.

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

## Floating background-task cards

Every authenticated page polls active background work and shows compact floating cards until it finishes. Work for the open workspace appears at the lower right. Work for one or more other accessible workspaces appears in differently coloured lower-left cards, grouped by workspace name; changing the active workspace moves each running task to the appropriate side. Each card preserves its expanded or minimized state when moving between modules or reloading the page.

Each card shows the task, its current stage and progress when the job reports one. The red circular **Stop Job** control is available only for interruptible work in a workspace the user can access and asks for confirmation before requesting a stop. Browser dataset uploads retain their latest measured percentage between progress events and can be interrupted while their request is active; dataset jobs already accepted by the server then appear separately and can be stopped at their safe checkpoints. Report, Chart Set, Auto-calculated Field and combined-CDR work use the same cooperative stop behaviour. A stopped duplication removes its partial workspace; stopped exports remove temporary output; imports cannot be stopped after importing has begun.

## Small screens

The interface targets compact screens around the iPhone 13 base viewport (`390 × 844`).

- Panels use reduced side margins.
- Forms and action bars stack vertically.
- Dataset Management changes to a readable card-like table layout.
- Chart navigation appears below the chart and before Interactive Preview.
- Wide tables scroll inside their own containers rather than widening the page.
- Workspace Management remains visible when expanded.

On a phone, use portrait orientation for forms and landscape orientation when inspecting a very wide data table.

## Dashboard navigation and overlays

The analytical tabs are ordered **Datasets Analysis → E2E Dashboards → E2E Reporting** for users with access. Datasets Analysis uses blue, E2E Dashboards uses muted violet, and Reporting uses brighter purple. E2E Reporting is shown only to super-admins and the EJAITUR user when a workspace is active; other users do not see it in the top navigation or Modules menu. The dashboard viewer groups charts by Slide and opens the same Dashboard Filters controls in a floating panel. Its dataset dialog provides pagination and CSV export.

App Logs is available from the utility navigation and includes App Events for the active workspace plus the live Execution Log for the running server. See [App Logs](app-logs.md).
