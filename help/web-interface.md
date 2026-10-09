# Web Interfaces

The UI uses a shared header, module tabs, panels, dialogs and tables. Read [Product Overview](overview.md) for the purpose of each module.

> [!NOTE]
> **Role-sensitive navigation.** Sections and actions depend on your role and workspace access. A hidden administrative module does not indicate missing data.

> [!TIP]
> **Long-running work.** Floating task cards follow server-side work while you navigate. Minimizing a card does not stop its task.

## In this guide

| Task or topic | Go to |
| --- | --- |
| Navigation | [Open section](#navigation) |
| Header controls | [Open section](#header-controls) |
| Panels | [Open section](#panels) |
| Searchable selectors | [Open section](#searchable-selectors) |
| Filter Builder | [Open section](#filter-builder) |
| Tables | [Open section](#tables) |
| Dialogs and progress | [Open section](#dialogs-and-progress) |
| Floating background-task cards | [Open section](#floating-background-task-cards) |
| Unassigned values card | [Open section](#unassigned-values-card) |
| Small screens | [Open section](#small-screens) |
| Dashboard navigation and overlays | [Open section](#dashboard-navigation-and-overlays) |

## Navigation

Administrative tabs occupy the upper row, aligned to the left. Primary module tabs occupy the lower row, directly beside the first content panel. The same order applies on smaller screens.

Primary tabs, in their default order (super-admins change their order, titles, icons and colours in **Admin → Interface Settings**):

- **Workspace**
- CDR Analysis
- E2E Dashboards
- Reporting (old)
- Scoring & GAP Analysis
- Network Insights
- Non-Qualified Calls (in development, hidden until activated)
- **Reporting**
- **Builders** (dropdown with Chart Builder and Query Builder)

Each main tab is a feature. **Admin → Features Activation** makes it available to all users or to nobody by default, plus Allowed and Forbidden roles, user groups and users (Forbidden wins); a feature that is not active for an account disappears from its tabs and Modules menu, and its pages and API answer 403. When the tabs do not fit on one line they wrap onto further lines, and main module tabs never share a line with the administrative tabs.

Other tabs:

- Help
- App Logs
- Config (dropdown with Application Config and Workspace Config), for `user-editor`, `admin` and `super-admin` roles
- Admin, for `admin` and `super-admin` roles

Help Home opens by default after login. Help, the Readme and the Changelog are also available without signing in, with a **Sign in** link. Every module except Workspace requires an open workspace.

Open **Builders** to choose **Chart Builder** or **Query Builder**. The Modules sidebar links to each builder directly. Within its Administrative Modules group, Application Logs is first and Administrator Config is last. The top tab for Administrator Config remains **Admin**.

Move the pointer near a viewport edge to reveal a collapsed Modules, Sections, Navigation or Releases tab. An invisible hover area beside each tab responds even while background tasks are running; task cards leave that edge clear. The tabs recede when the pointer leaves, and keyboard focus also reveals them.

Modules uses nearly the full viewport height when needed and scrolls if the window is too short for every entry. In Help, Sections lists the current document's headings.

Open **Config** and choose **Application Config** for application-wide runtime settings or **Workspace Config** for Report Templates Management, Operator Mappings, Vendor Mappings, Spectrum Holdings, Main Cities and the Scoring hierarchy/KPI/GAP settings in the active workspace. Workspace Config's Page Sections navigator jumps between the panels.

Help Navigation lists unnumbered documents under General, Main Modules, Administrative Modules and Reference. Main Modules follow the order of the main tabs, by default: [Workspace Management](workspace-management.md), CDR Analysis, E2E Dashboards, Reporting (old), Scoring & GAP Analysis, Network Insights, Non-Qualified Calls, [Reporting](reporting.md), Chart Builder and Query Builder. Docker Deployment follows Deployment Configuration in General. App Logs is the first administrative document and Administrator Config is the last. Readme and Changelog open Reference before Project Structure and Roadmap.

The Help Home link stays above the groups. Every chapter is available to every reader except Reporting (old), which only users with that feature see.

The Changelog adds a **Releases** list that jumps to each release; it highlights the release being read, as Help Navigation highlights the open document. Both lists grow down to the end of the document and only scroll beyond it.

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

The shared Filter Builder is used by Chart Builder, Reporting (old) Chart Preview and Report Template Chart Preview.

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

Server-transfer dialogs can be hidden with **Hide** while the transfer continues as a background task, and are restored after a browser reload while the transfer remains active. On the destination, once the package has arrived, a dialog without **Hide** keeps every open page out of use until the import ends; on the source, the dialog comes back once when that import starts and can be hidden again.

## Floating background-task cards

Every authenticated page polls active background work and shows compact floating cards until it finishes. Work for the open workspace appears at the lower right. Work for one or more other accessible workspaces appears in differently coloured lower-left cards, grouped by workspace name; changing the active workspace moves each running task to the appropriate side.

Each card preserves its expanded or minimized state when moving between modules or reloading the page.

Each card shows the task, its current stage and progress when the job reports one. The red circular **Stop Job** control is available only for interruptible work in a workspace the user can access and asks for confirmation before requesting a stop.

Browser dataset uploads retain their latest measured percentage between progress events and can be interrupted while their request is active; dataset jobs already accepted by the server then appear separately and can be stopped at their safe checkpoints. Report, Chart Set, Auto-calculated Field and combined-CDR work use the same cooperative stop behaviour.

A stopped duplication removes its partial workspace; stopped exports remove temporary output; imports cannot be stopped after importing has begun.

## Unassigned values card

While the ready CDRs of the open workspace have Operators, Vendors or Campaigns that no Operator, Vendor or Campaign Map assigns, a red card at the lower right of every page lists them until they are assigned. Editors open the assignment table from its buttons; the user-viewer role is asked to inform an administrator. See [Unassigned values warning](workspace-config.md#unassigned-values-warning).

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

By default the analytical tabs are ordered **CDR Analysis** → **E2E Dashboards** → **Reporting (old)** → **Scoring & GAP Analysis** → **Network Insights** → **Non-Qualified Calls** → **Reporting** for users with each feature. CDR Analysis uses blue, Network Insights electric indigo, E2E Dashboards muted violet, Scoring & GAP Analysis the navy-to-green gradient of its header, Non-Qualified Calls raspberry, **Reporting** green and Reporting (old) brighter purple; Network Insights and Non-Qualified Calls also use their colour for their header, buttons, tables and dialogs. Once a super-admin turns them on in **Admin → Interface Settings** (they are off on a new deployment), module tabs show their stage in a small label in the top-right corner, without taking space from their name: a red **ALPHA** while in development (Network Insights and Non-Qualified Calls), a yellow **BETA** while being validated (**Reporting** and **Builders**) and a blue **NEW** with a star once consolidated (Scoring & GAP Analysis); established modules (Workspace, CDR Analysis and E2E Dashboards) have no label. Super-admins choose in Interface Settings the order of the main tabs, the title of each one and its short title for narrow windows, its icon and its colour, and the label of each module with its colour and optional icon, or hide every label. Each module header shows a subtle decoration that represents the module (for example CDF curves in CDR Analysis or an antenna with radio waves in Network Insights) and is only as tall as its content; the controls of the module, such as the workspace or dataset selectors, follow in their own panel. The administrative tabs (Help, App Logs, Config and Admin) show an icon too, and the main tabs cover their lower part so both rows show the same tab height. Scoring offers NR Mode and CDR selection, aggregation controls, saved background jobs and tables/charts/GAP exports. Network Insights analyses RSRP/SINR, coverage and interference maps, sites, spectrum and network deployment. Each main tab shows a representative icon before its name. On narrower windows the main tabs switch to their short names (Analysis, Dashboards, Reporting, Scoring, Network) and then drop their icons, so the tab rows never overlap.

**Reporting** and Reporting (old) are shown only to the users, roles and groups they are activated for in Admin → Features Activation; a new deployment activates **Reporting** for everyone and Reporting (old) for nobody. The dashboard viewer groups charts by Slide and opens the same Dashboard Filters controls in a floating panel. Its dataset dialog provides pagination and CSV export.

App Logs is available from the utility navigation and includes App Events for the active workspace plus the live Execution Log for the running server. See [App Logs](app-logs.md).
