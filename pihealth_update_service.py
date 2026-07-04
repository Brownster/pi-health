"""Framework-neutral orchestration for the Pi-Health self-update.

Drives the privileged update steps (pull, deps, migrate, build, restart) one at
a time through an injected ``helper_call`` and yields progress events shaped for
the background-operation SSE transport (``operation_manager`` / ``operation_sse``).

The final restart tears down the process that is streaming these events, so the
restart is scheduled with a short delay by the helper and this generator emits a
terminal ``restarting`` event *before* returning. The frontend then polls
``/api/health`` until the new build answers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

HelperCall = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]

_SHORT = 8


def _short(commit: str | None) -> str:
    return (commit or "")[:_SHORT] or "unknown"


def stream_update(helper_call: HelperCall, config: Mapping[str, Any]):
    """Yield operation events while running the self-update through the helper.

    Each yielded dict carries a ``step`` label plus either a human ``line``, an
    ``error`` (terminal), or a ``done`` terminal marker. A failed step yields an
    ``error`` event and stops; a successful run ends with a terminal event that
    either reports "already up to date" or signals the pending restart.
    """

    def call(step: str) -> Mapping[str, Any]:
        params = dict(config)
        params["step"] = step
        try:
            return helper_call("pihealth_update", params) or {}
        except Exception as exc:  # transport/helper failure surfaces as a step error
            return {"success": False, "error": str(exc)}

    # -- pull ----------------------------------------------------------------
    yield {"step": "pull", "line": "Pulling latest code…"}
    pull = call("pull")
    if not pull.get("success"):
        yield {"step": "pull", "error": pull.get("error", "git pull failed")}
        return

    old_commit = pull.get("old_commit")
    new_commit = pull.get("new_commit")
    changed = list(pull.get("changed_files") or [])

    if old_commit and new_commit and old_commit == new_commit:
        yield {
            "step": "pull",
            "line": f"Already up to date ({_short(new_commit)}); no restart needed.",
            "new_commit": new_commit,
            "done": True,
        }
        return

    yield {
        "step": "pull",
        "line": f"Updated {_short(old_commit)} → {_short(new_commit)} ({len(changed)} file(s) changed).",
    }

    # -- dependencies (only when requirements changed) -----------------------
    if "requirements.txt" in changed:
        yield {"step": "deps", "line": "Installing Python dependencies…"}
        deps = call("deps")
        if not deps.get("success"):
            yield {"step": "deps", "error": deps.get("error", "dependency install failed")}
            return
        yield {
            "step": "deps",
            "line": f"Dependencies skipped ({deps.get('reason', '')})."
            if deps.get("skipped")
            else "Dependencies installed.",
        }
    else:
        yield {"step": "deps", "line": "No dependency changes."}

    # -- runtime migration (idempotent; always attempted) --------------------
    yield {"step": "migrate", "line": "Applying runtime migrations…"}
    migrate = call("migrate")
    if not migrate.get("success"):
        yield {"step": "migrate", "error": migrate.get("error", "migration failed")}
        return
    yield {
        "step": "migrate",
        "line": f"Migration skipped ({migrate.get('reason', '')})."
        if migrate.get("skipped")
        else "Runtime migration complete.",
    }

    # -- UI bundle (only when the frontend changed) --------------------------
    if any(path.startswith("frontend/") for path in changed):
        yield {"step": "build", "line": "Rebuilding web UI…"}
        build = call("build")
        if not build.get("success"):
            yield {"step": "build", "error": build.get("error", "UI build failed")}
            return
        yield {
            "step": "build",
            "line": f"UI build skipped ({build.get('reason', '')}); using committed bundle."
            if build.get("skipped")
            else "Web UI rebuilt.",
        }
    else:
        yield {"step": "build", "line": "No UI changes."}

    # -- restart (terminal) --------------------------------------------------
    yield {"step": "restart", "line": "Restarting service…"}
    restart = call("restart")
    if not restart.get("success"):
        yield {"step": "restart", "error": restart.get("error", "service restart failed")}
        return

    yield {
        "step": "restart",
        "line": f"Service restarting — reconnecting to {_short(new_commit)}…",
        "restarting": True,
        "new_commit": new_commit,
        "done": True,
    }
