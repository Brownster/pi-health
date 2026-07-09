"""Framework-neutral app-catalog reads, install, and remove.

Owns catalog loading, template rendering, dependency checks, and the
install/remove orchestration (including per-stack locking and streaming startup).
The Flask blueprint in :mod:`catalog_manager` is a thin transport adapter that
supplies environment-specific providers and maps results/errors to HTTP.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from compose_yaml import ComposeYamlError
from media_layout import MediaLayout, resolve_layout_default
from operation_manager import parse_sse_payload

TEMPLATE_VAR_PATTERN = re.compile(r'\{\{(\w+)\}\}')
CATALOG_COMPOSE_SECTIONS = ('networks', 'volumes', 'configs', 'secrets')


class CatalogError(Exception):
    """Carries a JSON-ready payload and HTTP status for a catalog failure."""

    def __init__(self, payload: dict, status_code: int):
        self.payload = payload
        self.status_code = status_code
        super().__init__(payload.get('error', 'Catalog error'))


class CatalogComposeSectionError(ValueError):
    def __init__(self, code, message, status_code):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def _summarize_item(item: Mapping[str, Any]) -> dict:
    summary = {
        'id': item.get('id'),
        'name': item.get('name') or item.get('id'),
        'description': item.get('description', ''),
        'kind': item.get('kind', 'app'),
        'requires': item.get('requires', []) or [],
        'disabled_by_default': bool(item.get('disabled_by_default', False)),
        'source': item.get('_source', ''),
    }
    if item.get('kind') == 'bundle':
        summary['members'] = item.get('members', []) or []
    return summary


def _render_template(service_dict, values):
    """Replace {{KEY}} placeholders with values in a deep copy."""
    def substitute(obj):
        if isinstance(obj, str):
            def replacer(match):
                key = match.group(1)
                return str(values.get(key, match.group(0)))
            return TEMPLATE_VAR_PATTERN.sub(replacer, obj)
        elif isinstance(obj, dict):
            return {k: substitute(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [substitute(item) for item in obj]
        return obj

    return substitute(service_dict)


def _find_unresolved_placeholders(obj, path=""):
    """Find unresolved {{KEY}} placeholders in a rendered template."""
    unresolved = []
    if isinstance(obj, str):
        for match in TEMPLATE_VAR_PATTERN.finditer(obj):
            unresolved.append(f"{path}{match.group(0)}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            unresolved.extend(_find_unresolved_placeholders(value, f"{path}{key}."))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            unresolved.extend(_find_unresolved_placeholders(value, f"{path}[{idx}]."))
    return unresolved


def _merge_compose_section(compose_data, section, section_data):
    """Merge one validated catalog resource section without overwriting users."""
    if section not in CATALOG_COMPOSE_SECTIONS:
        raise CatalogComposeSectionError(
            'invalid_catalog_section', f'Catalog section is not managed: {section}', 400
        )
    if not isinstance(section_data, dict):
        raise CatalogComposeSectionError(
            'invalid_catalog_section', f'Catalog {section} section must be a mapping', 400
        )
    if not section_data:
        return

    if section not in compose_data:
        compose_data[section] = {}
    elif not isinstance(compose_data.get(section), dict):
        raise CatalogComposeSectionError(
            'compose_section_conflict',
            f'Existing Compose {section} section must be a mapping',
            409,
        )

    for key, value in section_data.items():
        if key in compose_data[section] and compose_data[section][key] != value:
            raise CatalogComposeSectionError(
                'compose_resource_conflict',
                f'Compose {section} resource already has a different definition: {key}',
                409,
            )

    for key, value in section_data.items():
        compose_data[section].setdefault(key, value)


def _validate_install_request(item, values):
    """Fill defaults and confirm required fields have values."""
    for field in item.get('fields', []):
        key = field.get('key')
        if not key:
            continue
        required = field.get('required', True)
        if key not in values or values[key] == '':
            default = field.get('default', '')
            if default == '' and required:
                return False, f"Missing required field: {field.get('label', key)}"
            if default != '':
                values[key] = default
    return True, None


def _field_default_from_layout(field: Mapping[str, Any], layout: MediaLayout) -> str | None:
    token = field.get("layout_default")
    if token:
        return resolve_layout_default(layout, str(token))

    legacy_mapping = {
        'CONFIG_DIR': 'config_root',
        'DOWNLOADS_DIR': 'downloads_root',
        'MEDIA_DIR': 'storage_root',
        'STORAGE_DIR': 'storage_root',
        'BACKUP_DIR': 'backup_root',
    }
    key = field.get('key', '')
    mapped = legacy_mapping.get(key)
    if mapped:
        return resolve_layout_default(layout, mapped)
    return None


def _apply_layout_defaults(item: Mapping[str, Any], media_paths: Mapping[str, Any]) -> dict:
    """Return an item copy with field defaults derived from the media layout."""
    layout = MediaLayout.from_media_paths(media_paths)
    item_copy = dict(item)
    if 'fields' not in item_copy:
        return item_copy
    item_copy['fields'] = []
    for field in item.get('fields', []):
        field_copy = dict(field)
        default = _field_default_from_layout(field_copy, layout)
        if default is not None:
            field_copy['default'] = default
        item_copy['fields'].append(field_copy)
    return item_copy


def _check_dependencies(item, installed_services):
    """Return (satisfied, missing_deps) for an item against installed services."""
    requires = item.get('requires', []) or []
    missing = [dep for dep in requires if dep not in installed_services]
    return len(missing) == 0, missing


class CatalogService:
    """Read the catalog and install/remove services through injected ports."""

    def __init__(
        self,
        *,
        catalog_dir_provider: Callable[[], str],
        media_paths_loader: Callable[[], dict],
        load_stack_compose: Callable[[str], tuple],
        save_stack_compose: Callable[..., str],
        list_stacks: Callable[[], tuple],
        get_stack_path: Callable[[str], str],
        validate_stack_name: Callable[[str], tuple],
        backup_stack: Callable[[str], Any],
        run_compose_command: Callable[..., tuple],
        stream_compose_command: Callable[[str, str], Any],
        stack_lock: Callable[[str], Any],
        compose_conflict_error: type,
        path_exists: Callable[[str], bool] = os.path.exists,
        is_dir: Callable[[str], bool] = os.path.isdir,
    ) -> None:
        self._catalog_dir_provider = catalog_dir_provider
        self._media_paths_loader = media_paths_loader
        self._load_stack_compose = load_stack_compose
        self._save_stack_compose = save_stack_compose
        self._list_stacks = list_stacks
        self._get_stack_path = get_stack_path
        self._validate_stack_name = validate_stack_name
        self._backup_stack = backup_stack
        self._run_compose_command = run_compose_command
        self._stream_compose_command = stream_compose_command
        self._stack_lock = stack_lock
        self._ComposeFileConflictError = compose_conflict_error
        self._path_exists = path_exists
        self._is_dir = is_dir

    # -- Catalog reads -------------------------------------------------------

    def _load_catalog_items(self) -> list[dict]:
        import yaml

        items = []
        catalog_dir = os.path.abspath(self._catalog_dir_provider())
        if not self._is_dir(catalog_dir):
            return items
        for root, dirnames, filenames in os.walk(catalog_dir):
            dirnames.sort()
            for filename in sorted(filenames):
                if not (filename.endswith('.yaml') or filename.endswith('.yml')):
                    continue
                path = os.path.join(root, filename)
                try:
                    with open(path) as handle:
                        data = yaml.safe_load(handle)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                if not data.get('id'):
                    continue
                data['_source'] = os.path.relpath(path, catalog_dir)
                items.append(data)
        return items

    def _get_catalog_item(self, item_id):
        for item in self._load_catalog_items():
            if item.get('id') == item_id:
                return item
        return None

    def list_items(self) -> dict:
        return {'items': [_summarize_item(item) for item in self._load_catalog_items()]}

    def get_item(self, item_id, *, apply_media_paths: bool = False) -> dict:
        item = self._get_catalog_item(item_id)
        if not item:
            raise CatalogError({'error': 'Catalog item not found'}, 404)

        if apply_media_paths:
            item = _apply_layout_defaults(item, self._media_paths_loader())

        return {'item': item}

    def status(self) -> dict:
        services = sorted(set(self._list_stack_services()))
        service_map = {
            service: sorted(set(self._find_service_stacks(service)))
            for service in services
        }
        return {'services': services, 'service_stacks': service_map}

    def check_dependencies(self, data: Mapping[str, Any]) -> dict:
        item_id = data.get('id')
        if not item_id:
            raise CatalogError({'error': 'Missing app id'}, 400)
        item = self._get_catalog_item(item_id)
        if not item:
            raise CatalogError({'error': f'Catalog item not found: {item_id}'}, 404)
        target_stack = data.get('target_stack')
        installed_services = (
            self._list_stack_services(target_stack)
            if target_stack
            else self._list_stack_services()
        )
        satisfied, missing = _check_dependencies(item, installed_services)
        return {
            'id': item_id,
            'requires': item.get('requires', []) or [],
            'satisfied': satisfied,
            'missing': missing,
            'installed_services': installed_services,
        }

    # -- Stack service discovery ---------------------------------------------

    def _list_stack_services(self, stack_name=None):
        services = []
        stacks, err = self._list_stacks()
        if err:
            return services
        for stack in stacks:
            name = stack.get('name')
            if stack_name and name != stack_name:
                continue
            try:
                data, _ = self._load_stack_compose(self._get_stack_path(name))
            except (ComposeYamlError, self._ComposeFileConflictError):
                continue
            if not data:
                continue
            stack_services = data.get('services', {})
            if isinstance(stack_services, dict):
                services.extend(stack_services.keys())
        return services

    def _find_service_stacks(self, service_name):
        stacks, err = self._list_stacks()
        if err:
            return []
        matches = []
        for stack in stacks:
            name = stack.get('name')
            try:
                data, _ = self._load_stack_compose(self._get_stack_path(name))
            except (ComposeYamlError, self._ComposeFileConflictError):
                continue
            if not data:
                continue
            services = data.get('services', {})
            if isinstance(services, dict) and service_name in services:
                matches.append(name)
        return matches

    # -- Install -------------------------------------------------------------

    def install(self, data, *, operation_registry, owner, username) -> tuple[dict, int]:
        item_id = data.get('id')
        if not item_id:
            raise CatalogError({'error': 'Missing app id'}, 400)
        item = self._get_catalog_item(item_id)
        if not item:
            raise CatalogError({'error': f'Catalog item not found: {item_id}'}, 404)
        if item.get('kind') == 'bundle':
            raise CatalogError(
                {
                    'error': 'Bundle install requires the media quickstart flow',
                    'id': item_id,
                },
                400,
            )

        target_stack = data.get('target_stack')
        lock_name = (
            target_stack
            if target_stack and target_stack != 'new'
            else data.get('stack_name') or item_id
        )
        valid, error = self._validate_stack_name(lock_name)
        if not valid:
            raise CatalogError({'error': error}, 400)

        with self._stack_lock(lock_name):
            return self._install_locked(
                data, item, operation_registry=operation_registry,
                owner=owner, username=username,
            )

    def _install_locked(self, data, item, *, operation_registry, owner, username):
        item_id = data.get('id')
        values = dict(data.get('values', {}))
        item = _apply_layout_defaults(item, self._media_paths_loader())

        valid, error = _validate_install_request(item, values)
        if not valid:
            raise CatalogError({'error': error}, 400)

        target_stack = data.get('target_stack')
        new_stack_name = data.get('stack_name') or item_id

        if target_stack and target_stack != 'new':
            valid, error = self._validate_stack_name(target_stack)
            if not valid:
                raise CatalogError({'error': error}, 400)
            stack_dir = self._get_stack_path(target_stack)
            if not self._is_dir(stack_dir):
                raise CatalogError({'error': f'Stack not found: {target_stack}'}, 404)
            active_stack = target_stack
        else:
            valid, error = self._validate_stack_name(new_stack_name)
            if not valid:
                raise CatalogError({'error': error}, 400)
            stack_dir = self._get_stack_path(new_stack_name)
            if self._path_exists(stack_dir):
                raise CatalogError({'error': f'Stack already exists: {new_stack_name}'}, 409)
            active_stack = new_stack_name

        installed_services = self._list_stack_services(active_stack)
        if not data.get('skip_dependency_check', False):
            satisfied, missing = _check_dependencies(item, installed_services)
            if not satisfied:
                raise CatalogError({
                    'error': 'Missing dependencies',
                    'missing_dependencies': missing,
                    'message': f'Install these first in stack {active_stack}: {", ".join(missing)}',
                }, 400)

        if item_id in installed_services:
            raise CatalogError(
                {'error': f'Service already installed in stack {active_stack}: {item_id}'}, 409
            )

        rendered_service = _render_template(item.get('service', {}), values)
        unresolved = _find_unresolved_placeholders(rendered_service)
        if unresolved:
            raise CatalogError(
                {'error': 'Template has unresolved variables', 'unresolved': unresolved}, 400
            )

        try:
            compose_data, compose_path = self._load_stack_compose(stack_dir)
        except self._ComposeFileConflictError as exc:
            raise CatalogError(exc.as_dict(), 409) from exc
        except ComposeYamlError as exc:
            raise CatalogError({
                'code': 'invalid_compose_yaml',
                'error': 'Cannot update invalid Compose YAML',
                'message': str(exc),
            }, 400) from exc
        if compose_data is None:
            compose_data = {'version': '3.8', 'services': {}}

        if 'services' not in compose_data:
            compose_data['services'] = {}
        elif not isinstance(compose_data.get('services'), dict):
            raise CatalogError({
                'code': 'compose_section_conflict',
                'error': 'Existing Compose services section must be a mapping',
            }, 409)

        try:
            for section in CATALOG_COMPOSE_SECTIONS:
                if section not in item:
                    continue
                rendered_section = _render_template(item.get(section), values)
                unresolved_section = _find_unresolved_placeholders(rendered_section)
                if unresolved_section:
                    raise CatalogError({
                        'error': 'Template has unresolved variables',
                        'unresolved': unresolved_section,
                    }, 400)
                _merge_compose_section(compose_data, section, rendered_section)
        except CatalogComposeSectionError as exc:
            raise CatalogError({'code': exc.code, 'error': str(exc)}, exc.status_code) from exc

        backup_file = None
        if self._path_exists(stack_dir):
            backup_file = self._backup_stack(active_stack)

        compose_data['services'][item_id] = rendered_service

        try:
            self._save_stack_compose(stack_dir, compose_data, compose_path)
        except Exception as exc:
            raise CatalogError(
                {'error': f'Failed to save compose file: {exc}', 'backup': backup_file}, 500
            ) from exc

        result = {
            'status': 'installed',
            'id': item_id,
            'name': item.get('name', item_id),
            'backup': backup_file,
            'stack': active_stack,
        }

        if not data.get('start_service', False):
            return result, 200

        def produce_events():
            for frame in self._stream_compose_command(active_stack, 'up'):
                payload = parse_sse_payload(frame)
                if payload is not None:
                    yield payload

        try:
            operation = operation_registry.create(
                owner=owner,
                username=username,
                kind='catalog-install',
                target=active_stack,
                producer=produce_events,
            )
        except RuntimeError as exc:
            result.update({
                'error': f'App was installed but startup could not be scheduled: {exc}',
                'started': False,
            })
            raise CatalogError(result, 500) from exc

        result.update({
            'operation_id': operation.operation_id,
            'stream_url': f'/api/catalog/operations/{operation.operation_id}/stream',
        })
        return result, 202

    # -- Remove --------------------------------------------------------------

    def remove(self, data) -> dict:
        item_id = data.get('id')
        if not item_id:
            raise CatalogError({'error': 'Missing app id'}, 400)

        target_stack = data.get('target_stack')
        if target_stack:
            valid, error = self._validate_stack_name(target_stack)
            if not valid:
                raise CatalogError({'error': error}, 400)
            try:
                target_compose, _ = self._load_stack_compose(self._get_stack_path(target_stack))
            except self._ComposeFileConflictError as exc:
                raise CatalogError(exc.as_dict(), 409) from exc
            except ComposeYamlError as exc:
                raise CatalogError({
                    'code': 'invalid_compose_yaml',
                    'error': 'Cannot update invalid Compose YAML',
                    'message': str(exc),
                }, 400) from exc
            target_services = (target_compose or {}).get('services', {})
            if not isinstance(target_services, dict) or item_id not in target_services:
                raise CatalogError({'error': f'Service not found in stack: {target_stack}'}, 404)
            active_stack = target_stack
        else:
            stacks, stacks_error = self._list_stacks()
            if stacks_error:
                raise CatalogError({'error': stacks_error}, 500)
            conflicted_stack = next(
                (
                    stack for stack in stacks
                    if stack.get('code') == self._ComposeFileConflictError.code
                ),
                None,
            )
            if conflicted_stack:
                raise CatalogError({
                    'code': self._ComposeFileConflictError.code,
                    'error': (
                        f'Cannot locate service while stack '
                        f'{conflicted_stack["name"]} has multiple Compose files'
                    ),
                    'stack': conflicted_stack['name'],
                    'files': conflicted_stack['compose_files'],
                }, 409)
            stacks_with_service = self._find_service_stacks(item_id)
            if not stacks_with_service:
                raise CatalogError({'error': f'Service not installed: {item_id}'}, 404)
            if len(stacks_with_service) > 1:
                raise CatalogError(
                    {'error': 'Service exists in multiple stacks', 'stacks': stacks_with_service},
                    409,
                )
            active_stack = stacks_with_service[0]

        with self._stack_lock(active_stack):
            return self._remove_locked(data, item_id, active_stack)

    def _remove_locked(self, data, item_id, active_stack):
        if data.get('check_dependents', True):
            dependents = []
            items = self._load_catalog_items()
            stack_services = self._list_stack_services(active_stack)
            for installed_id in stack_services:
                if installed_id == item_id:
                    continue
                for cat_item in items:
                    if cat_item.get('id') == installed_id:
                        if item_id in (cat_item.get('requires', []) or []):
                            dependents.append(installed_id)
                        break
            if dependents:
                raise CatalogError({
                    'error': 'Cannot remove: other services depend on this',
                    'dependents': dependents,
                    'message': f'Remove these first: {", ".join(dependents)}',
                }, 400)

        stack_dir = self._get_stack_path(active_stack)
        try:
            compose_data, compose_path = self._load_stack_compose(stack_dir)
        except self._ComposeFileConflictError as exc:
            raise CatalogError(exc.as_dict(), 409) from exc
        except ComposeYamlError as exc:
            raise CatalogError({
                'code': 'invalid_compose_yaml',
                'error': 'Cannot update invalid Compose YAML',
                'message': str(exc),
            }, 400) from exc
        if compose_data is None:
            raise CatalogError({'error': 'Compose file not found'}, 404)
        services = compose_data.get('services', {})
        if not isinstance(services, dict) or item_id not in services:
            raise CatalogError({'error': f'Service not installed: {item_id}'}, 404)

        stop_result = None
        if data.get('stop_service', True):
            stop_result, stop_error = self._run_compose_command(
                active_stack, 'stop', service=item_id
            )
            if stop_error:
                raise CatalogError({'error': f'Failed to stop service: {stop_error}'}, 409)
            if not stop_result or not stop_result.get('success'):
                detail = (stop_result or {}).get('stderr') or 'Compose stop failed'
                raise CatalogError(
                    {'error': f'Failed to stop service: {detail}', 'stop_result': stop_result}, 409
                )

        backup_file = self._backup_stack(active_stack)

        if 'services' in compose_data and item_id in compose_data['services']:
            del compose_data['services'][item_id]

        try:
            self._save_stack_compose(stack_dir, compose_data, compose_path)
        except Exception as exc:
            raise CatalogError(
                {'error': f'Failed to save compose file: {exc}', 'backup': backup_file}, 500
            ) from exc

        result = {
            'status': 'removed',
            'id': item_id,
            'backup': backup_file,
            'stack': active_stack,
        }
        if stop_result:
            result['stop_result'] = stop_result
        return result
