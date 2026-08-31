# Configuration

Dashboard Analytic reads its runtime configuration from environment variables. For Docker deployments, set them in `docker/.env`; for local runs, export them in the shell or use the project environment file if your local setup provides one.

## Application and access

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Name shown by the application. |
| `APP_PORT` | Port exposed by the production service. |
| `APP_DEV_PORT` | Port used by the development service. |
| `APP_SECRET_KEY` | Secret used to protect signed session data. Use a unique, private value outside local development. |
| `APP_ADMIN_USERNAME` | Initial administrator account name. |
| `APP_ADMIN_PASSWORD` | Initial administrator password. Change the default before sharing the deployment. |

## Persistent storage

| Variable | Purpose |
| --- | --- |
| `CONFIG_DIR` | Root directory for shared configuration, including the initial/legacy database and shared Slides Templates. Defaults to `config/` under the project. |
| `DATA_DIR` | Root directory for workspace data, registry and temporary transfer packages. Defaults to `data/` under the project. |
| `ASSETS_DIR` | Root directory for bundled assets, including the PowerPoint master templates. Defaults to `assets/` under the project. |
| `APP_DATABASE_PATH` | Initial/legacy SQLite location. Each open workspace uses its own database; the workspace registry is stored at `data/workspaces/workspace-registry.db`. |
| `APP_INPUT_DIR` | Initial/legacy input location used when migrating an existing installation. |
| `APP_OUTPUT_DIR` | Initial/legacy output location retained only for migration compatibility; current workspaces do not use an `output/` directory. |
| `APP_EXPORT_DIR` | Initial/legacy export location used when migrating an existing installation. |
| `APP_SLIDES_TEMPLATES_DIR` | Optional override for the shared editable Slides Templates library. |
| `APP_PPT_TEMPLATES_DIR` | Optional override for the bundled PowerPoint master-template directory. |

Set `CONFIG_DIR`, `DATA_DIR` and `ASSETS_DIR` when the three roots live outside the project; the more specific `APP_*` variables above override an individual location when necessary. The service process must have read/write access to the configured storage directories. In Docker, mount both `config/` and `data/`: shared Slides Templates live in `config/`, while the registry and every workspace are stored under `data/workspaces/`. Each workspace has its database, `input/` and `exports/` directories. The version and release date displayed in the application are maintained in `src/version.py` and the changelog, not through an environment variable.

## Recommended deployment setup

1. Copy the Docker environment example to `docker/.env` if it is not already present.
2. Set a strong `APP_SECRET_KEY` and administrator password.
3. Select persistent host paths or named volumes for `config/` and `data/`.
4. Start the stack and log in with the configured administrator account.
5. Verify that an uploaded CDR remains visible after restarting the service.

Do not commit real passwords, secret keys or customer data to source control.
