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
| `APP_DATABASE_PATH` | Initial/legacy SQLite location. The application registry is stored alongside it as `workspace-registry.db`; each open workspace uses its own database. |
| `APP_INPUT_DIR` | Initial/legacy input location used when migrating an existing installation. |
| `APP_OUTPUT_DIR` | Initial/legacy output location used when migrating an existing installation. |
| `APP_EXPORT_DIR` | Initial/legacy export location used when migrating an existing installation. |
| `APP_SLIDES_TEMPLATES_DIR` | Optional override for the seed Slides Templates library copied into newly created workspaces. |
| `APP_PPT_TEMPLATES_DIR` | Optional override for the bundled PowerPoint master-template directory. |

The service process must have read/write access to the configured storage directories. In Docker, mount both `config/` and `data/`: the registry and seed templates live in `config/`, while every workspace is stored in `data/workspaces/<Workspace Name>/` with its database, input, output, exports and editable Slides Templates. The version and release date displayed in the application are maintained in `src/version.py` and the changelog, not through an environment variable.

## Recommended deployment setup

1. Copy the Docker environment example to `docker/.env` if it is not already present.
2. Set a strong `APP_SECRET_KEY` and administrator password.
3. Select persistent host paths or named volumes for `config/` and `data/`.
4. Start the stack and log in with the configured administrator account.
5. Verify that an uploaded CDR remains visible after restarting the service.

Do not commit real passwords, secret keys or customer data to source control.
