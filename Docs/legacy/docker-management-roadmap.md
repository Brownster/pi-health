# Docker Management Roadmap (pi-health vs Dockge)

Purpose
- Provide a feature-parity roadmap and implementation guidance.
- Target audience: junior devs implementing missing features.

Scope (what we reviewed)
- pi-health backend: `app.py`, `compose_editor.py`
- pi-health frontend: `static/containers.html`, `static/edit.html`
- Dockge reference: `dockge/README.md`

Current pi-health capabilities (baseline)
- System health dashboard: CPU/mem/disk/network/temp.
- Container list + start/stop/restart.
- Container logs viewer.
- Per-container network diagnostics.
- Compose file editor (single `DOCKER_COMPOSE_PATH`).
- Auth (session-based login).

Dockge features missing in pi-health
- Stack-oriented management (compose.yaml per stack).
- Scan/import existing stacks directory.
- Interactive editor with YAML validation.
- Real-time pull/up/down output.
- Web terminal in UI.
- Docker run -> compose.yaml conversion.
- Multiple Docker hosts (agents).

Roadmap (phased delivery)

Phase 1 - Stack foundation (core parity)
Goal
- Manage stacks (compose files) instead of a single file.

Suggested environment variables
- `STACKS_PATH=/opt/stacks` (root folder for stacks)
- `STACK_FILE=compose.yaml` (default file name)

Data model
- A stack is a directory containing `compose.yaml` or `docker-compose.yml`.

Backend API (Flask)
- `GET /api/stacks` -> list stacks
- `POST /api/stacks/scan` -> re-scan filesystem
- `GET /api/stacks/<stack>/compose` -> get compose content
- `POST /api/stacks/<stack>/compose` -> save compose content
- `POST /api/stacks/<stack>/up` -> docker compose up -d
- `POST /api/stacks/<stack>/down` -> docker compose down
- `POST /api/stacks/<stack>/restart` -> docker compose restart
- `DELETE /api/stacks/<stack>` -> delete stack directory

Implementation notes
- Use `subprocess.run` with `cwd=stack_path` and `-f` if file name is not default.
- Validate stack names to prevent path traversal.

Suggested helper functions (pseudo-code)
```python
STACKS_PATH = os.getenv("STACKS_PATH", "/opt/stacks")
STACK_FILENAMES = ["compose.yaml", "docker-compose.yml"]

def list_stacks():
    stacks = []
    for entry in os.listdir(STACKS_PATH):
        stack_dir = os.path.join(STACKS_PATH, entry)
        if not os.path.isdir(stack_dir):
            continue
        compose_file = find_compose_file(stack_dir)
        if compose_file:
            stacks.append({"name": entry, "path": stack_dir, "file": compose_file})
    return stacks

def find_compose_file(stack_dir):
    for filename in STACK_FILENAMES:
        path = os.path.join(stack_dir, filename)
        if os.path.exists(path):
            return path
    return None

# security: stack name whitelist
STACK_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
```

Frontend
- Add a new `stacks.html` page.
- Table with stack name, status, and actions (up/down/restart/edit/delete).

Phase 2 - Real-time compose output
Goal
- Show live output for `pull`, `up`, `down` operations.

Backend
- Use Server-Sent Events (SSE) or WebSocket.
- Run compose command via `subprocess.Popen` and stream stdout lines.

SSE example (outline)
```python
@app.route("/api/stacks/<name>/up/stream")
def stack_up_stream(name):
    def generate():
        proc = subprocess.Popen(
            ["docker", "compose", "up", "-d"],
            cwd=stack_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            yield f"data: {line.rstrip()}\n\n"
        proc.wait()
        yield f"data: [done:{proc.returncode}]\n\n"
    return Response(generate(), mimetype="text/event-stream")
```

Frontend
- Use `EventSource` to stream output into a log pane.

Phase 3 - Editor upgrade (interactive)
Goal
- YAML editor with syntax highlighting and validation.

Approach
- Use a browser editor like Monaco or CodeMirror.
- Validate YAML with a client-side parser and show inline errors.

Notes
- Keep backend validation as a safety net.
- Add compose backup/restore per stack.

Phase 3 implementation plan (minimal scope)
- Frontend: replace textarea with Monaco or CodeMirror on `stacks.html` (Compose + .env tabs).
- Frontend: add YAML validation on change; surface inline errors + a top-level error banner.
- Frontend: add "Restore backup" UI with a dropdown of recent backups and a preview.
- Backend: add `GET /api/stacks/<name>/backups` to list recent backups.
- Backend: add `GET /api/stacks/<name>/backups/<filename>` to fetch backup content.
- Backend: add `POST /api/stacks/<name>/restore` to restore selected backup.
- Backend: validate YAML on save (server-side) and return clear error messages.

Fix current bug
- `compose_editor.py` uses `datetime` and `shutil` but does not import them.

Phase 4 - Web terminal
Goal
- Provide a terminal UI that shells into containers.

Backend
- WebSocket endpoint that executes `docker exec -it <container> sh`.
- Use `pty` to support interactive sessions.

Frontend
- Use xterm.js to render the terminal.

Phase 5 - Docker run -> compose conversion
Goal
- Convert `docker run` commands into compose YAML.

Approach
- Use a parser library or implement a small parser for common flags.
- Provide conversion UI with editable output.

Phase 6 - Multi-host agents
Goal
- Manage multiple Docker daemons from one UI.

Approach
- Store multiple host configs (name, Docker endpoint, auth).
- Proxy actions per host, or run lightweight agents on each host.

Risk and complexity notes
- Streaming output and terminal require careful access control.
- Path traversal and command injection must be handled in all stack operations.
- Support for rootless Docker or Podman may require command differences.

Testing guidance
- Unit test: stack name validation, stack discovery.
- Integration test: compose up/down against a small sample stack.
- UI test: confirm output streaming and error handling.

Deliverables for Phase 1 (minimum parity slice)
- `GET /api/stacks` + `stacks.html` UI
- Stack CRUD + compose up/down/restart
- Per-stack compose editor and backup
