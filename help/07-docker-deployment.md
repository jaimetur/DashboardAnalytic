# Docker deployment

Docker Compose is the supported way to run Dashboard Analytic as a service. The compose files use `docker/.env` for runtime configuration. The Docker image includes the bundled PowerPoint master at `assets/ppt-templates/Template_CDR_analysis.pptx`.

Set the `TZ` variable in `docker/.env` to the server's IANA timezone (the default is `Europe/Madrid`). This controls the timezone used by the container for timestamps shown and stored by the application.

## Development

Run the development stack with a rebuild when dependencies or source code change:

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

Use this mode while developing or validating UI and API changes. Stop it with `Ctrl+C`.

## Production

Start the production stack in the background:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build
```

Inspect running services with `docker compose -f docker/docker-compose.yml ps` and use the same compose file with `logs -f` when diagnosing an issue.

## Persistent data

The workspace registry, shared Slides Templates library, workspace databases, uploaded sources and exports must persist outside the container filesystem. The compose configuration mounts both `config/` and `data/`; confirm that the host directories are writable by Docker and included in the backup policy. In particular, back up `config/slides-templates/` and the complete `data/workspaces/` tree (including `workspace-registry.db`). Admin **Import/Export** can also produce portable ZIP backups.

Before the first production start, set a private `APP_SECRET_KEY`, a non-default administrator password and the required storage paths in `docker/.env`. See [Configuration](01-configuration-file.md) for the variable reference.

## Updating safely

1. Back up the persistent database and data directories.
2. Pull or obtain the intended application revision.
3. Rebuild and start the production compose stack.
4. Log in, open an existing workspace and verify that its datasets, templates and database data are available.
5. Generate a small test export before processing production CDRs.
