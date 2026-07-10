#!/usr/bin/env sh
set -eu

docker compose --env-file docker/.env -f docker/docker-compose-dev.yml up --build
