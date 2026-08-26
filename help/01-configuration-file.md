# Configuration

Dashboard Analytic reads its runtime configuration from environment variables. For Docker deployments, set them in `docker/.env`; for local runs, export them in the shell or use the project environment file if your local setup provides one.

## Application and access

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Name shown by the application. |
| `APP_VERSION` | Version shown in the interface and diagnostic information. |
| `APP_PORT` | Port exposed by the production service. |
| `APP_DEV_PORT` | Port used by the development service. |
| `APP_SECRET_KEY` | Secret used to protect signed session data. Use a unique, private value outside local development. |
| `APP_ADMIN_USERNAME` | Initial administrator account name. |
| `APP_ADMIN_PASSWORD` | Initial administrator password. Change the default before sharing the deployment. |

## Persistent storage

| Variable | Purpose |
| --- | --- |
| `APP_DATABASE_PATH` | SQLite database containing users, workspace metadata and processed datasets. |
| `APP_INPUT_DIR` | Uploaded source files. |
| `APP_OUTPUT_DIR` | Generated analysis artefacts. |
| `APP_EXPORT_DIR` | Downloadable exports, including generated reports. |
| `APP_REPORTING_TEMPLATE_DIR` | Optional override for the bundled PowerPoint template directory. |

The service process must have read/write access to the configured storage directories. In Docker, mount them as volumes so that uploaded data and generated reports survive a container replacement.

## Recommended deployment setup

1. Copy the Docker environment example to `docker/.env` if it is not already present.
2. Set a strong `APP_SECRET_KEY` and administrator password.
3. Select persistent host paths or named volumes for the database, inputs and exports.
4. Start the stack and log in with the configured administrator account.
5. Verify that an uploaded CDR remains visible after restarting the service.

Do not commit real passwords, secret keys or customer data to source control.
