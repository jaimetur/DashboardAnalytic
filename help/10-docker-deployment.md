# Docker deployment

Docker Compose is the recommended service deployment. Production pulls a published image; development mounts source and enables reload.

## Before deployment

- Install Docker Engine and Compose.
- Create persistent host directories for configuration and data.
- Copy or prepare `docker/.env`.
- Set a private `APP_SECRET_KEY`.
- Set the correct IANA `TZ` value.
- Confirm that port `7278` is available or map another host port.

## Production

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --pull always
```

The production stack:

- uses `${IMAGE_REPOSITORY}:${IMAGE_TAG}`;
- applies the configured pull policy;
- mounts persistent config/data paths;
- includes the bundled PowerPoint master;
- runs without source-code bind mounts;
- supports native AMD64 and ARM64 images.

## Development

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

Use development mode for source changes. It is not the recommended production configuration.

## Example environment

```env
APP_NAME=Dashboard Analytic
APP_PORT=7278
APP_DEV_PORT=7279
APP_SECRET_KEY=replace-this-value
APP_CONFIG_DIR=/app/config
APP_DATA_DIR=/app/data
APP_ASSETS_DIR=/app/assets
TZ=Europe/Madrid

HOST_CONFIG_DIR=/volume1/docker/stacks/dashboardanalytic/config
HOST_DATA_DIR=/volume1/docker/stacks/dashboardanalytic/data

IMAGE_REPOSITORY=jaimetur/dashboard-analytic
IMAGE_TAG=latest
CONTAINER_NAME=dashboardanalytic
```

## Persistence

Persist both roots:

- Config: users, permissions, transfer offers and Slides Templates.
- Data: workspace registry, databases, uploads, reports, Chart Sets and transfer packages.

Do not rely on the writable container layer. Recreating a container must not remove application state.

## Operations

Status:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml ps
```

Logs:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml logs -f
```

Restart:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml restart
```

Inspect the published architectures:

```bash
docker buildx imagetools inspect IMAGE_REPOSITORY:IMAGE_TAG
```

## Safe upgrade

1. Back up the complete host config and data directories.
2. Record the currently running image digest.
3. Select the intended image tag.
4. Pull and recreate the service.
5. Verify the image ID/digest actually running.
6. Sign in and check users, permissions and templates.
7. Open an existing workspace and inspect its size/datasets.
8. Generate a small Chart Set or report.

Database migrations run automatically at startup. For example, legacy Report/Chart job tables are merged into `generated_jobs` and removed.

## Build cache and stale-image checks

Build cache should retain unchanged dependency layers but must not hide committed source changes.

If local source behaves differently from the container:

- confirm the change was committed before the workflow ran;
- check the workflow built the expected commit SHA;
- inspect the pulled image digest;
- run `docker compose pull`;
- recreate, rather than only restart, the container;
- verify `IMAGE_TAG` and repository spelling;
- generate new output instead of inspecting files from an older job.

## Server-to-server connectivity

For direct transfers:

- the source browser must reach its own application;
- the source server must reach the destination URL and port;
- the destination must expose the transfer API through its proxy/firewall;
- URL hostnames must resolve inside the source container/network;
- use HTTPS unless operating on a trusted private network;
- a destination super-admin must be logged in to approve the offer.

Remember that `localhost` inside a container refers to that container, not the Docker host or another server.

## Backup scope

At minimum, back up:

```text
config/application.db
config/slides-templates/
data/workspaces/workspace-registry.db
data/workspaces/<workspace>/
```

Admin Export / Import provides portable backups, but infrastructure-level backups are still recommended.

See [Configuration](03-configuration.md) for the complete variable reference.
