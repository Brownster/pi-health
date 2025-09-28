# Docker MCP Server

Implements `docker_ps`, `compose_ps`, `compose_restart`, `compose_start`, `compose_stop` via the Docker SDK and `docker compose` CLI.

Env vars: `COMPOSE_FILE` (optional path to compose file). Requires access to the Docker socket.
