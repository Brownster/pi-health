"""Data-driven media-stack seed configuration service."""

from __future__ import annotations

import configparser
import json
import os
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

import yaml

from arr_client import ArrClient, read_api_key
from catalog_service import _render_template
from media_layout import MediaLayout, resolve_layout_default


class MediaSeedError(Exception):
    """Raised when a media stack cannot be seeded."""


ClientFactory = Callable[[str, Mapping[str, Any], str], Any]
MediaServerClientFactory = Callable[[str, Mapping[str, Any], str | None], Any]
ApiKeyReader = Callable[[str], str]
TextReader = Callable[[str], str]
TextWriter = Callable[[str, str], None]


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
        media_server_client_factory: MediaServerClientFactory | None = None,
        text_reader: TextReader | None = None,
        text_writer: TextWriter | None = None,
        path_exists: Callable[[str], bool] = os.path.exists,
    ) -> None:
        self._catalog_dir_provider = catalog_dir_provider
        self._stack_path_provider = stack_path_provider
        self._load_stack_compose = load_stack_compose
        self._layout_provider = layout_provider
        self._api_key_reader = api_key_reader
        self._client_factory = client_factory or _default_client_factory
        self._media_server_client_factory = (
            media_server_client_factory or _default_media_server_client_factory
        )
        self._text_reader = text_reader or _read_text
        self._text_writer = text_writer or _write_text_atomic
        self._path_exists = path_exists

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
            return self._seed_indexer(service_id, seed, installed_services)
        if kind == "downloadclient":
            return self._seed_download_client(service_id, seed)
        if kind == "mediaserver":
            return self._seed_media_server(service_id, seed)
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

    def _seed_indexer(
        self,
        service_id: str,
        seed: Mapping[str, Any],
        installed_services: set[str],
    ) -> dict[str, Any]:
        client = self._client_for(service_id, seed)
        changes = 0
        lines: list[str] = []

        existing_apps = {
            (
                str(application.get("implementation", "")).lower(),
                str(application.get("name", "")).lower(),
            )
            for application in client.list_applications()
        }
        for application in seed.get("applications", []):
            if not isinstance(application, dict):
                continue
            app_service = str(application.get("service", "")).lower()
            implementation = str(application.get("implementation", ""))
            if app_service not in installed_services:
                lines.append(f"Skipped {implementation}: service not installed")
                continue
            name = implementation or app_service
            key = (implementation.lower(), name.lower())
            if key in existing_apps:
                continue
            api_key = self._api_key_reader(str(application.get("config_file", "")))
            client.add_application(_indexer_application_payload(application, api_key))
            existing_apps.add(key)
            changes += 1
            lines.append(f"Added {implementation} application")

        if not lines:
            lines.append("Already configured")
        return {"changes": changes, "lines": lines}

    def _seed_download_client(
        self,
        service_id: str,
        seed: Mapping[str, Any],
    ) -> dict[str, Any]:
        implementation = str(seed.get("implementation", ""))
        api = seed.get("api", {})
        config_file = str(api.get("config_file", "")) if isinstance(api, dict) else ""
        if not config_file:
            return {"changes": 0, "lines": [f"Skipped {implementation}: no local config file"]}
        if not self._path_exists(config_file):
            return {"changes": 0, "lines": [f"Skipped {implementation}: config file not found"]}
        if implementation.lower() == "transmission":
            return self._seed_transmission_config(config_file, seed)
        if implementation.lower() == "sabnzbd":
            return self._seed_sabnzbd_config(config_file, seed)
        return {"changes": 0, "lines": [f"Skipped {service_id}: local seeding unsupported"]}

    def _seed_transmission_config(
        self,
        config_file: str,
        seed: Mapping[str, Any],
    ) -> dict[str, Any]:
        config = self._read_json_config(config_file)
        downloads = seed.get("downloads", {})
        if not isinstance(downloads, dict):
            downloads = {}
        desired = {
            "download-dir": str(downloads.get("complete_dir", "/downloads/complete")),
        }
        if downloads.get("incomplete_dir"):
            desired["incomplete-dir"] = str(downloads["incomplete_dir"])
            desired["incomplete-dir-enabled"] = True

        changes = _apply_mapping_updates(config, desired)
        if not changes:
            return {"changes": 0, "lines": ["Transmission local config already seeded"]}
        self._text_writer(config_file, json.dumps(config, indent=2, sort_keys=True) + "\n")
        return {
            "changes": changes,
            "lines": [f"Updated Transmission local config {config_file}"],
        }

    def _seed_sabnzbd_config(
        self,
        config_file: str,
        seed: Mapping[str, Any],
    ) -> dict[str, Any]:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        if self._path_exists(config_file):
            parser.read_string(self._text_reader(config_file))
        if not parser.has_section("misc"):
            parser.add_section("misc")

        downloads = seed.get("downloads", {})
        if not isinstance(downloads, dict):
            downloads = {}
        desired = {
            "complete_dir": str(downloads.get("complete_dir", "/downloads/complete")),
        }
        if downloads.get("incomplete_dir"):
            desired["download_dir"] = str(downloads["incomplete_dir"])

        changes = 0
        for key, value in desired.items():
            if parser.get("misc", key, fallback=None) == value:
                continue
            parser.set("misc", key, value)
            changes += 1

        if not changes:
            return {"changes": 0, "lines": ["SABnzbd local config already seeded"]}
        from io import StringIO

        output = StringIO()
        parser.write(output)
        self._text_writer(config_file, output.getvalue())
        return {
            "changes": changes,
            "lines": [f"Updated SABnzbd local config {config_file}"],
        }

    def _seed_media_server(
        self,
        service_id: str,
        seed: Mapping[str, Any],
    ) -> dict[str, Any]:
        client = self._media_server_client_for(service_id, seed)
        changes = 0
        lines: list[str] = []

        existing_libraries = {
            (
                str(library.get("name", "")).lower(),
                str(library.get("collection_type", "")).lower(),
            ): {
                str(path).rstrip("/")
                for path in library.get("paths", [])
            }
            for library in client.list_libraries()
            if isinstance(library, dict)
        }
        for library in seed.get("libraries", []):
            if not isinstance(library, dict):
                continue
            name = str(library.get("name", "")).strip()
            collection_type = str(library.get("kind", "")).strip()
            path = str(library.get("path", "")).rstrip("/")
            if not name or not collection_type or not path:
                continue
            if _path_is_under(path, "/downloads"):
                raise MediaSeedError(f"{service_id} library may not be under {path}")
            key = (name.lower(), collection_type.lower())
            if path in existing_libraries.get(key, set()):
                continue
            client.create_library(
                name=name,
                collection_type=collection_type,
                paths=[path],
            )
            existing_libraries.setdefault(key, set()).add(path)
            changes += 1
            lines.append(f"Added Jellyfin {name} library at {path}")

        if not lines:
            lines.append("Jellyfin libraries already seeded")
        return {"changes": changes, "lines": lines}

    def _client_for(self, service_id: str, seed: Mapping[str, Any]) -> Any:
        api = seed.get("api", {})
        if not isinstance(api, dict):
            raise MediaSeedError(f"{service_id} seed is missing api settings")
        config_file = str(api.get("config_file", ""))
        api_key = self._api_key_reader(config_file)
        return self._client_factory(service_id, seed, api_key)

    def _media_server_client_for(self, service_id: str, seed: Mapping[str, Any]) -> Any:
        api = seed.get("api", {})
        if not isinstance(api, dict):
            raise MediaSeedError(f"{service_id} seed is missing api settings")
        api_key = None
        api_key_file = str(api.get("api_key_file", "") or api.get("config_file", ""))
        if api_key_file:
            api_key = self._api_key_reader(api_key_file)
        return self._media_server_client_factory(service_id, seed, api_key)

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

    def _read_json_config(self, config_file: str) -> dict[str, Any]:
        if not self._path_exists(config_file):
            return {}
        try:
            data = json.loads(self._text_reader(config_file))
        except json.JSONDecodeError as exc:
            raise MediaSeedError(f"Invalid JSON config {config_file}: {exc}") from exc
        if not isinstance(data, dict):
            raise MediaSeedError(f"JSON config must be an object: {config_file}")
        return data


def _default_client_factory(service_id: str, seed: Mapping[str, Any], api_key: str) -> ArrClient:
    api = seed.get("api", {})
    return ArrClient(port=int(api["port"]), api_key=api_key)


def _default_media_server_client_factory(
    service_id: str,
    seed: Mapping[str, Any],
    api_key: str | None,
) -> "JellyfinClient":
    api = seed.get("api", {})
    if service_id != "jellyfin":
        raise MediaSeedError(f"{service_id} media server seeding is unsupported")
    return JellyfinClient(port=int(api["port"]), api_key=api_key)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _write_text_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _apply_mapping_updates(target: dict[str, Any], desired: Mapping[str, Any]) -> int:
    changes = 0
    for key, value in desired.items():
        if target.get(key) == value:
            continue
        target[key] = value
        changes += 1
    return changes


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


def _indexer_application_payload(
    application: Mapping[str, Any],
    api_key: str,
) -> dict[str, Any]:
    implementation = str(application.get("implementation", ""))
    service = str(application.get("service", "")).lower()
    port = int(application.get("port", 0))
    base_url = f"http://127.0.0.1:{port}" if port else f"http://{service}"
    return {
        "name": implementation or service,
        "implementation": implementation,
        "configContract": f"{implementation}Settings",
        "syncLevel": "fullSync",
        "tags": [],
        "fields": [
            {"name": "baseUrl", "value": base_url},
            {"name": "apiKey", "value": api_key},
            {"name": "syncCategories", "value": [5000, 5030, 5040]},
            {"name": "animeSyncCategories", "value": [5070]},
        ],
    }


class JellyfinClient:
    """Small wrapper over the Jellyfin library API."""

    def __init__(
        self,
        *,
        port: int,
        api_key: str | None = None,
        host: str = "127.0.0.1",
        transport: Callable[[str, str, Mapping[str, str], bytes | None], Any] | None = None,
    ) -> None:
        self._base_url = f"http://{host}:{port}"
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            self._headers["X-Emby-Token"] = api_key
        self._transport = transport or _jellyfin_urllib_transport

    def list_libraries(self) -> list[dict[str, Any]]:
        libraries = self._request("GET", "/Library/VirtualFolders")
        normalized = []
        for library in libraries if isinstance(libraries, list) else []:
            if not isinstance(library, dict):
                continue
            normalized.append(
                {
                    "name": library.get("Name") or library.get("name"),
                    "collection_type": (
                        library.get("CollectionType")
                        or library.get("collectionType")
                        or library.get("collection_type")
                    ),
                    "paths": (
                        library.get("Locations")
                        or library.get("locations")
                        or library.get("paths")
                        or []
                    ),
                }
            )
        return normalized

    def create_library(
        self,
        *,
        name: str,
        collection_type: str,
        paths: list[str],
    ) -> Any:
        query = urllib.parse.urlencode(
            {
                "name": name,
                "collectionType": collection_type,
                "paths": paths,
                "refreshLibrary": "false",
            },
            doseq=True,
        )
        return self._request("POST", f"/Library/VirtualFolders?{query}")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        normalized = path if path.startswith("/") else f"/{path}"
        return self._transport(method, f"{self._base_url}{normalized}", self._headers, body)


def _jellyfin_urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
) -> Any:
    from arr_client import urllib_transport

    return urllib_transport(method, url, headers, body)
