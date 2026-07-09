"""Data-driven media-stack seed configuration service."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import yaml

from arr_client import ArrClient, read_api_key
from catalog_service import _render_template
from media_layout import MediaLayout, resolve_layout_default


class MediaSeedError(Exception):
    """Raised when a media stack cannot be seeded."""


ClientFactory = Callable[[str, Mapping[str, Any], str], Any]
ApiKeyReader = Callable[[str], str]


class MediaSeedService:
    """Apply catalog ``seed:`` metadata to installed media services."""

    def __init__(
        self,
        *,
        catalog_dir_provider: Callable[[], str],
        stack_path_provider: Callable[[str], str],
        load_stack_compose: Callable[[str], tuple],
        layout_provider: Callable[[], MediaLayout],
        api_key_reader: ApiKeyReader = read_api_key,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._catalog_dir_provider = catalog_dir_provider
        self._stack_path_provider = stack_path_provider
        self._load_stack_compose = load_stack_compose
        self._layout_provider = layout_provider
        self._api_key_reader = api_key_reader
        self._client_factory = client_factory or _default_client_factory

    def seed_stack(self, stack_name: str = "media") -> Any:
        """Yield replayable operation events while applying media seed metadata."""
        try:
            yield {"step": "start", "line": f"Seeding media stack {stack_name}"}
            stack_dir = self._stack_path_provider(stack_name)
            compose_data, _ = self._load_stack_compose(stack_dir)
            if not compose_data:
                raise MediaSeedError(f"Stack not found or empty: {stack_name}")
            services = compose_data.get("services", {})
            if not isinstance(services, dict):
                raise MediaSeedError(f"Stack has no services: {stack_name}")

            catalog_items = self._catalog_items_by_id()
            seeded = 0
            changes = 0
            for service_id in services:
                item = catalog_items.get(service_id)
                seed = item.get("seed") if item else None
                if not isinstance(seed, dict):
                    continue
                resolved_seed = _render_template(seed, self._field_values(item))
                yield {
                    "step": service_id,
                    "line": f"Applying {resolved_seed.get('kind')} seed for {service_id}",
                }
                result = self._seed_service(service_id, resolved_seed, set(services))
                seeded += 1
                changes += result["changes"]
                for line in result["lines"]:
                    yield {"step": service_id, "line": line}

            yield {
                "step": "complete",
                "line": f"Seeded {seeded} service(s); {changes} change(s)",
                "seeded": seeded,
                "changes": changes,
                "done": True,
            }
        except Exception as exc:
            yield {"step": "error", "error": str(exc)}

    def _seed_service(
        self,
        service_id: str,
        seed: Mapping[str, Any],
        installed_services: set[str],
    ) -> dict[str, Any]:
        kind = seed.get("kind")
        if kind == "arr":
            return self._seed_arr(service_id, seed, installed_services)
        if kind == "indexer":
            return {"changes": 0, "lines": ["Indexer application seeding is pending"]}
        if kind == "downloadclient":
            return {"changes": 0, "lines": ["Download client local seeding is pending"]}
        if kind == "mediaserver":
            return {"changes": 0, "lines": ["Media server library seeding is pending"]}
        return {"changes": 0, "lines": [f"Unsupported seed kind: {kind}"]}

    def _seed_arr(
        self,
        service_id: str,
        seed: Mapping[str, Any],
        installed_services: set[str],
    ) -> dict[str, Any]:
        client = self._client_for(service_id, seed)
        changes = 0
        lines: list[str] = []

        forbidden = [str(path).rstrip("/") for path in seed.get("forbid_root_under", [])]
        for root in list(client.list_root_folders()):
            path = str(root.get("path", ""))
            root_id = root.get("id")
            if root_id is None:
                continue
            if any(_path_is_under(path, prefix) for prefix in forbidden):
                client.delete_root_folder(root_id)
                changes += 1
                lines.append(f"Removed forbidden root folder {path}")

        existing_roots = {
            str(root.get("path", "")).rstrip("/")
            for root in client.list_root_folders()
        }
        for path in seed.get("root_folders", []):
            path = str(path).rstrip("/")
            if any(_path_is_under(path, prefix) for prefix in forbidden):
                raise MediaSeedError(f"{service_id} root folder may not be under {path}")
            if path not in existing_roots:
                client.add_root_folder(path)
                changes += 1
                lines.append(f"Added root folder {path}")

        existing_clients = {
            (
                str(client_config.get("implementation", "")).lower(),
                _download_client_category(client_config),
            )
            for client_config in client.list_download_clients()
        }
        for client_config in seed.get("download_clients", []):
            if not isinstance(client_config, dict):
                continue
            implementation = str(client_config.get("implementation", ""))
            category = str(client_config.get("category", service_id))
            if implementation.lower() not in installed_services:
                lines.append(f"Skipped {implementation}: service not installed")
                continue
            key = (implementation.lower(), category)
            if key in existing_clients:
                continue
            client.add_download_client(_download_client_payload(client_config))
            existing_clients.add(key)
            changes += 1
            lines.append(f"Added {implementation} download client for {category}")

        client.set_media_management(
            import_mode=str(seed.get("import_mode", "")) or None,
            recycle_bin=str(seed.get("recycle_bin", "")) or None,
            completed_download_handling=seed.get("completed_download_handling"),
        )
        lines.append("Applied media management defaults")

        if seed.get("quality_profile"):
            client.set_quality_profile_default(str(seed["quality_profile"]))
            lines.append(f"Checked quality profile {seed['quality_profile']}")
        if seed.get("naming"):
            client.set_naming(str(seed["naming"]))
            lines.append(f"Applied naming preset {seed['naming']}")

        if not lines:
            lines.append("Already configured")
        return {"changes": changes, "lines": lines}

    def _client_for(self, service_id: str, seed: Mapping[str, Any]) -> Any:
        api = seed.get("api", {})
        if not isinstance(api, dict):
            raise MediaSeedError(f"{service_id} seed is missing api settings")
        config_file = str(api.get("config_file", ""))
        api_key = self._api_key_reader(config_file)
        return self._client_factory(service_id, seed, api_key)

    def _catalog_items_by_id(self) -> dict[str, dict]:
        items = {}
        catalog_dir = self._catalog_dir_provider()
        if not os.path.isdir(catalog_dir):
            return items
        for filename in os.listdir(catalog_dir):
            if not filename.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(catalog_dir, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    data = yaml.safe_load(handle)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("id"):
                items[str(data["id"])] = data
        return items

    def _field_values(self, item: Mapping[str, Any]) -> dict[str, str]:
        layout = self._layout_provider()
        values = {}
        for field in item.get("fields", []):
            key = field.get("key")
            if not key:
                continue
            if field.get("layout_default"):
                values[key] = resolve_layout_default(layout, str(field["layout_default"]))
            else:
                values[key] = str(field.get("default", ""))
        return values


def _default_client_factory(service_id: str, seed: Mapping[str, Any], api_key: str) -> ArrClient:
    api = seed.get("api", {})
    return ArrClient(port=int(api["port"]), api_key=api_key)


def _path_is_under(path: str, prefix: str) -> bool:
    clean_path = path.rstrip("/")
    clean_prefix = prefix.rstrip("/")
    return clean_path == clean_prefix or clean_path.startswith(f"{clean_prefix}/")


def _download_client_category(client_config: Mapping[str, Any]) -> str:
    if "category" in client_config:
        return str(client_config.get("category", ""))
    for field in client_config.get("fields", []):
        if not isinstance(field, dict):
            continue
        if str(field.get("name", "")).lower() == "category":
            return str(field.get("value", ""))
    return ""


def _download_client_payload(client_config: Mapping[str, Any]) -> dict[str, Any]:
    implementation = str(client_config.get("implementation", ""))
    category = str(client_config.get("category", ""))
    return {
        "name": implementation,
        "implementation": implementation,
        "configContract": f"{implementation}Settings",
        "enable": True,
        "removeCompletedDownloads": bool(client_config.get("remove_completed", True)),
        "removeFailedDownloads": bool(client_config.get("remove_failed", True)),
        "fields": [
            {"name": "category", "value": category},
        ],
    }
