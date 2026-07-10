# Docker Deployment

Development:

```bash
docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
```

Production:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d
```

The compose files mount `config` and `data` so that runtime state survives container recreation.
