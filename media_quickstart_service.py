"""One-shot media stack quickstart orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from catalog_service import CatalogError, _render_template
from media_layout import resolve_layout_default
from media_layout_service import MediaLayoutProvisionError


class MediaQuickstartError(Exception):
    """Raised when media quickstart cannot be prepared."""


class MediaQuickstartService:
    """Provision, install, start, and seed the bundled media stack."""

    def __init__(
        self,
        *,
        media_layout_service: Any,
        catalog_service: Any,
        stack_operations_service: Any,
        media_seed_service: Any,
        bundle_id: str = "media-server",
    ) -> None:
        self._media_layout_service = media_layout_service
        self._catalog_service = catalog_service
        self._stack_operations_service = stack_operations_service
        self._media_seed_service = media_seed_service
        self._bundle_id = bundle_id

    def stream_quickstart(
        self,
        *,
        stack_name: str = "media",
        values: Mapping[str, Any] | None = None,
        username: str = "unknown",
    ):
        """Yield replayable quickstart events."""
        values = values or {}
        try:
            yield {"step": "start", "line": f"Starting media quickstart for {stack_name}"}
            bundle = self._bundle()
            resolved = self._resolved_values(bundle, values)
            if str(resolved.get("USE_VPN", "true")).lower() != "true":
                raise MediaQuickstartError(
                    "USE_VPN=false is not supported by current media catalog entries"
                )

            yield {"step": "provision", "line": "Provisioning media folders"}
            provision = self._media_layout_service.provision(
                puid=resolved.get("PUID", "1000"),
                pgid=resolved.get("PGID", "1000"),
            )
            created_count = len(provision.get("created", []))
            existing_count = len(provision.get("existing", []))
            yield {
                "step": "provision",
                "line": (
                    f"Provisioned media folders "
                    f"({created_count} created, {existing_count} existing)"
                ),
            }

            installed = 0
            skipped = 0
            active_members = self._active_members(bundle, resolved)
            for index, member in enumerate(active_members):
                member_id = str(member["id"])
                install_data: dict[str, Any] = {
                    "id": member_id,
                    "values": _render_template(member.get("values", {}), resolved),
                    "start_service": False,
                    "skip_dependency_check": False,
                }
                if index == 0:
                    install_data["target_stack"] = "new"
                    install_data["stack_name"] = stack_name
                else:
                    install_data["target_stack"] = stack_name

                yield {"step": member_id, "line": f"Installing {member_id}"}
                try:
                    self._catalog_service.install(
                        install_data,
                        operation_registry=None,
                        owner="media-quickstart",
                        username=username,
                    )
                    installed += 1
                    yield {"step": member_id, "line": f"Installed {member_id}"}
                except CatalogError as exc:
                    if exc.status_code == 409 and "already installed" in str(exc).lower():
                        skipped += 1
                        yield {"step": member_id, "line": f"Skipped {member_id}: already installed"}
                        continue
                    raise

            yield {"step": "stack_up", "line": f"Starting stack {stack_name}"}
            for event in self._stack_operations_service.stream(stack_name, "up"):
                if event.get("error"):
                    raise MediaQuickstartError(str(event["error"]))
                if event.get("done"):
                    returncode = event.get("returncode")
                    if returncode not in (0, None):
                        raise MediaQuickstartError(
                            f"Stack startup failed with return code {returncode}"
                        )
                    yield {"step": "stack_up", "line": "Stack startup completed"}
                    continue
                if event.get("line"):
                    yield {"step": "stack_up", "line": event["line"]}

            yield {"step": "seed", "line": f"Seeding stack {stack_name}"}
            for event in self._media_seed_service.seed_stack(stack_name):
                if event.get("error"):
                    raise MediaQuickstartError(str(event["error"]))
                if event.get("done"):
                    yield {
                        "step": "seed",
                        "line": event.get("line", "Media seed completed"),
                        "changes": event.get("changes"),
                    }
                    continue
                yield {"step": "seed", "line": event.get("line", str(event))}

            yield {
                "step": "complete",
                "line": (
                    f"Media quickstart complete "
                    f"({installed} installed, {skipped} already installed)"
                ),
                "installed": installed,
                "skipped": skipped,
                "done": True,
            }
        except (CatalogError, MediaLayoutProvisionError, MediaQuickstartError) as exc:
            yield {"step": "error", "error": str(exc)}

    def _bundle(self) -> Mapping[str, Any]:
        item = self._catalog_service.get_item(self._bundle_id)["item"]
        if item.get("kind") != "bundle":
            raise MediaQuickstartError(f"Catalog item is not a bundle: {self._bundle_id}")
        return item

    def _resolved_values(
        self,
        bundle: Mapping[str, Any],
        overrides: Mapping[str, Any],
    ) -> dict[str, str]:
        layout = self._media_layout_service.layout()
        resolved: dict[str, str] = {}
        for key, value in bundle.get("shared_fields", {}).items():
            if isinstance(value, Mapping) and value.get("layout_default"):
                resolved[str(key)] = resolve_layout_default(layout, str(value["layout_default"]))
            else:
                resolved[str(key)] = str(value)
        for key, value in overrides.items():
            resolved[str(key)] = str(value)
        return resolved

    @staticmethod
    def _active_members(
        bundle: Mapping[str, Any],
        values: Mapping[str, str],
    ) -> list[Mapping[str, Any]]:
        members = [
            member
            for member in bundle.get("members", [])
            if isinstance(member, Mapping)
            and member.get("id")
            and _member_condition_matches(member, values)
        ]
        return sorted(members, key=lambda member: int(member.get("order", 0)))


def _member_condition_matches(
    member: Mapping[str, Any],
    values: Mapping[str, str],
) -> bool:
    condition = member.get("when")
    if not isinstance(condition, Mapping):
        return True
    field = str(condition.get("field", ""))
    expected = str(condition.get("equals", ""))
    return str(values.get(field, "")) == expected
