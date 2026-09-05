# Configuration

Dashboard Analytic reads defaults from `storage-paths.conf` and then applies environment-variable overrides. Use the file for source installations and `docker/.env` for Docker deployments.

## Runtime settings

| Variable | Purpose | Typical value |
| --- | --- | --- |
| `APP_NAME` | Product name shown in the header. | `Dashboard Analytic` |
| `APP_PORT` | Production service port. | `7278` |
| `APP_DEV_PORT` | Development service port. | `7279` |
| `APP_SECRET_KEY` | Session-signing secret. | A long private random value |
| `TZ` | Runtime timezone. | `Europe/Madrid` |

Always replace `APP_SECRET_KEY` outside local development.

## Storage settings

| Variable | Contains |
| --- | --- |
| `APP_CONFIG_DIR` | `application.db` and shared Slides Templates. |
| `APP_DATA_DIR` | Workspace registry, workspace directories and transfer packages. |
| `APP_ASSETS_DIR` | Static bundled assets and PowerPoint masters. |
| `HOST_CONFIG_DIR` | Host directory mounted at the container config path. |
| `HOST_DATA_DIR` | Host directory mounted at the container data path. |

Example local `storage-paths.conf`:

```text
APP_CONFIG_DIR = /srv/dashboard-analytic/config
APP_DATA_DIR = /srv/dashboard-analytic/data
APP_ASSETS_DIR = /srv/dashboard-analytic/assets
```

The application process must be able to read and write the configuration and data roots.

## Container settings

| Variable | Purpose |
| --- | --- |
| `IMAGE_REPOSITORY` | Docker image repository. |
| `IMAGE_TAG` | Image version to deploy. |
| `CONTAINER_NAME` | Running container name. |

Do not use an unpinned tag when a production change must be reproducible.

## Bootstrap accounts

A brand-new empty `application.db` creates these accounts once:

- `super / super123` — `super-admin`
- `admin / admin123` — `admin`
- `demo / demo123` — `user`

All three receive access to the `Default` workspace. Later restarts do not recreate deleted users or reset passwords.

After first login:

1. Click the username badge.
2. Change the bootstrap password.
3. Review roles and workspace access in Admin.
4. Store the secret and deployment configuration in the approved secret-management system.

## Validation checklist

- The header shows the expected application name and timezone-adjusted timestamps.
- A file uploaded to `Default` remains after a restart.
- Shared Slides Templates remain available after a restart.
- The workspace size badge and Workspace Management show matching values.
- `config/` and `data/` are included in backups.

Continue with [Docker Deployment](10-docker-deployment.md) for Compose examples.
