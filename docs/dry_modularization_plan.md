# DRY Modularization Plan for Pi-Health + Ops-Copilot

This document captures the refactoring plan used to modularize the Flask application into a DRY, service-oriented layout. It mirrors the implementation delivered in this iteration so future contributors can trace the intent behind the structure.

## Objectives and Non-Goals

### Objectives
- Extract business logic into reusable services.
- Introduce an application factory and blueprints.
- Add an AI provider interface to swap model backends.
- Centralize system stats and Docker logic for reuse by REST and MCP tools.
- Keep all public endpoints and UI behavior identical (no regressions).

### Non-Goals
- Server-side auth/CSRF (recommended later).
- New mutating tools or changes to approval semantics.
- Introducing a database (audit trail can be layered on later).

## Target Project Structure

```
app/
  __init__.py
  config.py
  routes/
    system.py
    containers.py
    ops_copilot.py
    compose_editor.py
  services/
    system_stats.py
    docker_service.py
    system_actions.py
ops_copilot/
  agent.py
  mcp.py
  providers.py
  registry.py
static/
app.py
```

The compose editor blueprint is now nested under `app/routes` and re-exported from the legacy `compose_editor.py` module for backward compatibility. MCP tooling is initialized through a registry so both HTTP routes and future MCP backends can share the same service logic.

## AI Provider Abstraction

`ops_copilot.providers` defines an `AIProvider` interface with `OpenAIProvider` and `OfflineProvider` implementations. The agent prefers the configured provider, then falls back to the inline OpenAI client, and finally renders an offline response. Injecting the provider allows new backends without changing orchestration code.

## MCP Tool Registry

`ops_copilot.registry.build_tools()` centralizes tool creation. The system stats tool now pulls metrics from the shared service module so REST endpoints and MCP workflows stay in sync.

## Application Factory

`app.create_app()` bootstraps the Flask app, loads configuration defaults, attaches the Ops-Copilot agent to `app.extensions`, registers blueprints, and recreates the static route surface expected by the UI. This makes testing and CLI usage easier while keeping runtime behavior stable.

## Configuration and Feature Flags

`app.config.Config` introduces environment-driven settings for AI credentials, disk paths, and the `ENABLE_SYSTEM_ACTIONS` feature flag. `system_actions` now respects the flag, returning a descriptive error when destructive operations are disabled.

## Logging and Audit

`app/logging.py` installs JSON logging with per-request IDs, attaches them to responses via `X-Request-ID`, and captures uncaught exceptions with contextual metadata. Approval requests now write JSONL audit entries to `APPROVAL_AUDIT_LOG` (default `logs/ops_copilot_approvals.log`), including timestamps, request IDs, remote address, and action outcomes for traceability.

## Future Work

- Rate limiting and extended audit instrumentation (e.g., chat history events).
- Additional MCP tools once the registry is extended.
