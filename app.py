from dataclasses import dataclass

from flask import (
    Blueprint,
    Flask,
    current_app,
    has_app_context,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
)
import os
import time
import psutil  # noqa: F401  (referenced as app.psutil in tests)
import docker
import subprocess
import socket
import json
import hmac
import secrets
import getpass
from urllib import request as urlrequest
from stack_manager import (
    default_stack_mutation_service,
    default_stack_operations_service,
    default_stack_read_service,
    stack_manager,
)
from auth_utils import (
    LoginRateLimiter,
    csrf_protect,
    get_csrf_token,
    load_users,
    login_required,
    rotate_csrf_token,
    verify_credentials as verify_password,
)
from catalog_manager import CATALOG_DIR, _load_stack_compose, catalog_manager, default_catalog_service
from catalog_service import CatalogService
from capability_api import capability_api
from capability_lifecycle_service import ExtensionLifecycleService
from capability_registry_service import CapabilityRegistryService
from capability_security import (
    CAPABILITY_PERMISSIONS,
    CapabilityAuthorizer,
    resolve_capability_roles,
)
from integrations_manager import integrations_manager
from mattermost_integration_service import MattermostIntegrationService
from stack_notifications_service import StackNotificationsService
from agent_integration_service import AgentIntegrationService
from alert_history import AlertEventLedger
from media_profile_service import MediaProfileService
from media_quickstart_service import MediaQuickstartService
from media_seed_service import MediaSeedService
from tools_manager import tools_manager, default_tools_service
from tools_service import ToolsService
from storage_plugins import default_storage_read_service, storage_bp
from storage_plugins.registry import init_plugins
from storage_capability_adapters import LegacyStorageCapabilityAdapter
from integration_capability_adapters import IntegrationCapabilityAdapter
from pi_monitor import get_pi_metrics
from update_scheduler import update_scheduler, init_scheduler, default_update_service
from update_service import AutoUpdateService
from backup_scheduler import backup_scheduler, init_backup_scheduler, default_backup_service
from backup_service import BackupService
from disk_manager import (
    default_disk_inventory_service,
    default_disk_mount_service,
    default_disk_summary_service,
    default_disk_suggestion_service,
    default_media_paths_service,
    default_seedbox_service,
    default_smart_service,
    disk_manager,
)
from disk_inventory_service import DiskInventoryService
from disk_summary_service import DiskSummaryService
from disk_mount_service import DiskMountService
from media_layout import DOWNLOAD_CATEGORIES, LIBRARY_KINDS
from media_paths_service import MediaPathsService
from media_layout_service import (
    MediaLayoutProvisionError,
    MediaLayoutService,
    MediaLayoutValidationError,
)
from seedbox_service import SeedboxService
from disk_suggestion_service import DiskSuggestionService
from smart_service import SmartService
from storage_read_service import StorageReadService
from setup_manager import setup_manager
from helper_client import helper_call
from operation_manager import OperationRegistry, OperationCapacityError
from operation_sse import stream_operation_response
from overview_service import OverviewService
from metric_history import InvalidMetricRange, MetricHistoryStore
from pihealth_update_service import stream_update as stream_pihealth_update
from ports import (
    AuditPort,
    Clock,
    ConfigRepository,
    DockerClientAdapter,
    DockerPort,
    FileAuditWriter,
    HelperClientAdapter,
    HelperPort,
    JsonFileRepository,
    SchedulerPort,
    monotonic_clock,
)
from system_service import SystemService
from stack_read_service import StackReadService
from stack_mutation_service import StackMutationService
from stack_operations_service import StackOperationsService
from container_inventory_service import ContainerInventoryService
from container_inventory_service import (
    ContainerInspectError,
    ContainerInspectNotFoundError,
    ContainerInspectUnavailableError,
)
from container_operations_service import ContainerOperationsService
from network_diagnostics_service import (  # noqa: F401  (several names re-exported for tests)
    ContainerNotFoundError,
    DockerUnavailableError,
    NetworkDiagnosticsService,
    command_missing,
    container_http_probe_script,
    exec_in_container,
    get_container_health,
    get_container_health_detail,
    get_container_local_ip as read_container_local_ip,
    get_container_public_ip as read_container_public_ip,
    run_container_fallback_probe as execute_container_fallback_probe,
    socket_probe as execute_socket_probe,
)
from network_group_service import NetworkGroupService
from container_helpers import (  # noqa: F401  (several names re-exported for tests)
    analyze_network_topology,
    calculate_container_cpu_percent,
    calculate_container_memory_stats,
    calculate_container_network_stats,
    get_container_ports,
    get_container_web_metadata,
    inherit_ports_from_network_service,
    parse_port_key,
)
from runtime_paths import (
    CONFIG_DIR as RUNTIME_CONFIG_DIR,
    INTEGRATIONS_CONFIG_DIR as RUNTIME_INTEGRATIONS_CONFIG_DIR,
    INTEGRATIONS_STATE_DIR as RUNTIME_INTEGRATIONS_STATE_DIR,
    STATE_DIR as RUNTIME_STATE_DIR,
    STORAGE_PLUGIN_CONFIG_DIR as RUNTIME_STORAGE_PLUGIN_CONFIG_DIR,
)
from system_stats import (  # noqa: F401  (several names re-exported for tests)
    _collect_disk_usage as collect_disk_usage,
    _cpu_percent_from_delta,
    _read_proc_stat_cpu,
    _safe_disk_usage,
    calculate_cpu_usage,
    get_cpu_usage_delta as read_cpu_usage_delta,
    get_cpu_usage_per_core,
    get_system_stats as collect_system_stats,
    get_temperature_fallback,
)
from werkzeug.utils import safe_join

core_api = Blueprint("core_api", __name__)

# Storage plugin configuration directory
STORAGE_PLUGIN_CONFIG_DIR = str(RUNTIME_STORAGE_PLUGIN_CONFIG_DIR)

PIHEALTH_UPDATE_CONFIG = str(RUNTIME_CONFIG_DIR / "pihealth_update.json")
MEDIA_LAYOUT_CONFIG = str(RUNTIME_CONFIG_DIR / "media_layout.json")
MEDIA_PROFILE_CONFIG = str(RUNTIME_CONFIG_DIR / "media_profile.json")
DEFAULT_PIHEALTH_UPDATE_CONFIG = {
    "repo_path": f"/home/{os.getenv('USER', 'pi')}/pi-health",
    "service_name": "pi-health"
}


def _load_pihealth_update_config():
    if os.path.exists(PIHEALTH_UPDATE_CONFIG):
        try:
            with open(PIHEALTH_UPDATE_CONFIG, "r") as handle:
                data = json.load(handle)
                return {**DEFAULT_PIHEALTH_UPDATE_CONFIG, **data}
        except Exception:
            return DEFAULT_PIHEALTH_UPDATE_CONFIG.copy()
    return DEFAULT_PIHEALTH_UPDATE_CONFIG.copy()


def _save_pihealth_update_config(config):
    os.makedirs(os.path.dirname(PIHEALTH_UPDATE_CONFIG), exist_ok=True)
    with open(PIHEALTH_UPDATE_CONFIG, "w") as handle:
        json.dump(config, handle, indent=2)

@dataclass(frozen=True)
class AppDependencies:
    users: dict[str, str]
    login_rate_limiter: LoginRateLimiter
    docker_client: object | None
    operation_registry: OperationRegistry | None = None
    clock: Clock = monotonic_clock
    helper: HelperPort | None = None
    docker: DockerPort | None = None
    scheduler: SchedulerPort | None = None
    audit: AuditPort | None = None
    config_repo: ConfigRepository | None = None
    system_service: SystemService | None = None
    container_inventory_service: ContainerInventoryService | None = None
    container_operations_service: ContainerOperationsService | None = None
    network_diagnostics_service: NetworkDiagnosticsService | None = None
    network_group_service: NetworkGroupService | None = None
    stack_read_service: StackReadService | None = None
    stack_mutation_service: StackMutationService | None = None
    stack_operations_service: StackOperationsService | None = None
    disk_inventory_service: DiskInventoryService | None = None
    disk_summary_service: DiskSummaryService | None = None
    disk_mount_service: DiskMountService | None = None
    media_paths_service: MediaPathsService | None = None
    media_layout_service: MediaLayoutService | None = None
    media_profile_service: MediaProfileService | None = None
    media_seed_service: MediaSeedService | None = None
    media_quickstart_service: MediaQuickstartService | None = None
    seedbox_service: SeedboxService | None = None
    disk_suggestion_service: DiskSuggestionService | None = None
    smart_service: SmartService | None = None
    storage_read_service: StorageReadService | None = None
    update_service: AutoUpdateService | None = None
    backup_service: BackupService | None = None
    catalog_service: CatalogService | None = None
    tools_service: ToolsService | None = None
    mattermost_integration_service: MattermostIntegrationService | None = None
    stack_notifications_service: StackNotificationsService | None = None
    agent_integration_service: AgentIntegrationService | None = None
    overview_service: OverviewService | None = None
    metric_history_service: MetricHistoryStore | None = None
    capability_registry_service: CapabilityRegistryService | None = None
    capability_roles: dict[str, str] | None = None
    capability_authorizer: object | None = None
    capability_lifecycle_service: object | None = None


def _default_system_service():
    return SystemService(
        cpu_reader=get_cpu_usage_delta,
        disk_collector=_collect_disk_usage,
        pi_metrics_reader=get_pi_metrics,
    )


def _default_capability_registry_service(application):
    if not application.config["INIT_PLUGINS"]:
        application.extensions["storage_capability_adapter"] = None
        application.extensions["integration_capability_adapter"] = None
        return CapabilityRegistryService(
            candidate_reader=lambda: (),
            limeos_version=application.config["LIMEOS_VERSION"],
        )
    storage_adapter = LegacyStorageCapabilityAdapter(STORAGE_PLUGIN_CONFIG_DIR)
    integration_adapter = IntegrationCapabilityAdapter(
        mattermost_status=application.extensions["mattermost_integration_service"].status,
        agent_status=application.extensions["agent_integration_service"].status,
    )
    application.extensions["storage_capability_adapter"] = storage_adapter
    application.extensions["integration_capability_adapter"] = integration_adapter

    def candidates():
        return [*storage_adapter.candidates(), *integration_adapter.candidates()]

    return CapabilityRegistryService(
        candidate_reader=candidates,
        limeos_version=application.config["LIMEOS_VERSION"],
    )


def _default_container_inventory_service(docker_port):
    return ContainerInventoryService(
        docker=docker_port,
        stats_reader=get_container_stats_cached,
        update_reader=lambda container_id: container_updates.get(container_id, False),
    )


def _default_media_layout_service(helper, repository):
    return MediaLayoutService(
        helper=helper,
        repository=repository,
        config_path_provider=lambda: MEDIA_LAYOUT_CONFIG,
    )


def _default_media_profile_service(repository):
    return MediaProfileService(
        repository=repository,
        profile_path_provider=lambda: MEDIA_PROFILE_CONFIG,
    )


def _default_media_seed_service(media_layout_service):
    from stack_manager import get_stack_path

    return MediaSeedService(
        catalog_dir_provider=lambda: CATALOG_DIR,
        stack_path_provider=get_stack_path,
        load_stack_compose=lambda stack_dir: _load_stack_compose(stack_dir),
        layout_provider=media_layout_service.layout,
    )


def _default_media_quickstart_service(
    media_layout_service,
    catalog_service,
    stack_operations_service,
    media_seed_service,
    media_profile_service,
):
    return MediaQuickstartService(
        media_layout_service=media_layout_service,
        catalog_service=catalog_service,
        stack_operations_service=stack_operations_service,
        media_seed_service=media_seed_service,
        media_profile_service=media_profile_service,
    )


def _default_mattermost_integration_service(repository, docker_port):
    from stack_manager import atomic_write_text, get_stack_path

    def container_status(name):
        if not docker_port.available:
            return None
        container = docker_port.get_container(name)
        if container is None:
            return None
        attrs = getattr(container, "attrs", {}) or {}
        health = ((attrs.get("State") or {}).get("Health") or {}).get("Status")
        return {"state": getattr(container, "status", "unknown"), "health": health}

    return MattermostIntegrationService(
        config_path=RUNTIME_INTEGRATIONS_CONFIG_DIR / "mattermost.json",
        secrets_path=RUNTIME_INTEGRATIONS_CONFIG_DIR / "mattermost.env",
        status_path=RUNTIME_INTEGRATIONS_STATE_DIR / "mattermost-status.json",
        stack_path_provider=get_stack_path,
        config_repository=repository,
        atomic_writer=atomic_write_text,
        container_status_provider=container_status,
        stack_notifications_config_path=RUNTIME_INTEGRATIONS_CONFIG_DIR
        / "stack-notifications.json",
        package_updates_config_path=RUNTIME_INTEGRATIONS_CONFIG_DIR
        / "package-updates.json",
    )


def _default_stack_notifications_service(repository):
    from alert_notifier import _default_poster

    config_path = RUNTIME_INTEGRATIONS_CONFIG_DIR / "stack-notifications.json"

    def config_provider():
        data = repository.read_json(config_path, default={})
        return data if isinstance(data, dict) else {}

    def config_writer(config):
        repository.write_json(config_path, dict(config), mode=0o600)

    return StackNotificationsService(
        config_provider=config_provider,
        poster=_default_poster,
        config_writer=config_writer,
    )


def _default_agent_integration_service(mattermost_service, docker_port, stack_read_service):
    from helper_client import helper_call

    def resources():
        containers = []
        if docker_port.available:
            try:
                containers = [
                    getattr(container, "name", "")
                    for container in docker_port.list_containers(all=True)
                ]
            except Exception:
                containers = []
        stacks = []
        try:
            listed, _error = stack_read_service.list_stacks()
            stacks = [item.get("name", "") for item in listed if isinstance(item, dict)]
        except Exception:
            pass
        return {"containers": containers, "stacks": stacks}

    return AgentIntegrationService(
        helper_call=helper_call,
        mattermost_status=mattermost_service.status,
        resource_provider=resources,
    )


def _default_overview_service(
    system_service,
    container_service,
    stack_service,
    mattermost_service,
    *,
    alert_history=None,
):
    alert_history = alert_history or AlertEventLedger(
        RUNTIME_INTEGRATIONS_STATE_DIR / "alert-events.jsonl"
    )
    return OverviewService(
        system_stats_provider=system_service.stats,
        container_provider=lambda: container_service.list_containers(include_stats=False),
        stack_provider=lambda: stack_service.list_with_status(include_status=True),
        alert_status_provider=mattermost_service.status,
        recent_recoveries_provider=lambda: alert_history.recent(event="recovery", limit=5),
    )


def _default_metric_history_service():
    return MetricHistoryStore(RUNTIME_STATE_DIR / "metrics.sqlite3")


def _write_container_update(container_id, update_available):
    container_updates[container_id] = update_available


def _default_container_operations_service(docker_port):
    return ContainerOperationsService(
        docker=docker_port,
        compose_runner=subprocess.run,
        update_writer=_write_container_update,
    )


def _container_operations():
    service = _extension("container_operations_service")
    if service is not None:
        return service
    return _default_container_operations_service(DockerClientAdapter(docker_client))


def _default_network_diagnostics_service(docker_port):
    return NetworkDiagnosticsService(
        docker=docker_port,
        command_runner=subprocess.run,
        socket_connector=socket.create_connection,
        urlopen=urlrequest.urlopen,
    )


def _network_diagnostics():
    service = _extension("network_diagnostics_service")
    if service is not None:
        return service
    return _default_network_diagnostics_service(DockerClientAdapter(docker_client))


def _default_network_group_service(docker_port):
    return NetworkGroupService(
        docker=docker_port,
        command_runner=subprocess.run,
        host_ip_reader=get_host_public_ip,
        container_ip_reader=get_container_public_ip,
    )


def _network_groups():
    service = _extension("network_group_service")
    if service is not None:
        return service
    return _default_network_group_service(DockerClientAdapter(docker_client))


def _default_dependencies():
    users = load_users()
    try:
        client = docker.from_env()
    except Exception as exc:
        print(f"Warning: Could not connect to Docker: {exc}")
        print("Docker functionality will be disabled")
        client = None
    # One shared clock drives both the rate limiter and the operation registry so
    # time can be controlled from a single seam in tests.
    clock = monotonic_clock
    return AppDependencies(
        users=users,
        login_rate_limiter=LoginRateLimiter(clock=clock),
        docker_client=client,
        operation_registry=OperationRegistry(clock=clock),
        clock=clock,
        helper=HelperClientAdapter(),
        docker=DockerClientAdapter(client),
        audit=FileAuditWriter(),
        config_repo=JsonFileRepository(),
        system_service=_default_system_service(),
    )


def _extension(name, fallback=None):
    if has_app_context():
        return current_app.extensions.get(name, fallback)
    return fallback


def _docker_client():
    return _extension("docker_client", docker_client)


def _docker_is_available():
    return _docker_client() is not None


def _login_rate_limiter():
    return _extension("login_rate_limiter")


def verify_credentials(username, password, users=None):
    """Verify username and password against configured users."""
    configured_users = users or _extension("auth_users")
    if not configured_users:
        return False
    return verify_password(configured_users, username, password)

# Compatibility fallbacks for helper functions called outside an app context.
docker_client = None
docker_available = False

# Track update status for containers
container_updates = {}

# Container stats cache with TTL
_container_stats_cache = {}
_container_stats_timestamps = {}
CONTAINER_STATS_TTL = 5  # seconds


def get_cpu_usage_delta(interval=0.1):
    """Read CPU deltas through the app's patchable stat reader."""
    return read_cpu_usage_delta(interval, stat_reader=_read_proc_stat_cpu)


def _collect_disk_usage(metric, path, warnings):
    """Collect disk usage through the app's patchable disk reader."""
    return collect_disk_usage(metric, path, warnings, disk_reader=_safe_disk_usage)


def get_system_stats():
    """Gather system statistics using app-level patchable dependencies."""
    return collect_system_stats(
        cpu_reader=get_cpu_usage_delta,
        disk_collector=_collect_disk_usage,
        pi_metrics_reader=get_pi_metrics,
    )


def get_container_stats_cached(container_id):
    """Fetch container stats with TTL caching."""
    now = time.time()

    # Check cache
    if container_id in _container_stats_cache:
        cached_time = _container_stats_timestamps.get(container_id, 0)
        if (now - cached_time) < CONTAINER_STATS_TTL:
            return _container_stats_cache[container_id]

    # Fetch fresh stats
    try:
        container = _docker_client().containers.get(container_id)
        if container.status != 'running':
            return None

        stats = container.stats(stream=False)

        result = {
            'cpu_percent': calculate_container_cpu_percent(stats),
            'memory': calculate_container_memory_stats(stats),
            'network': calculate_container_network_stats(stats)
        }

        _container_stats_cache[container_id] = result
        _container_stats_timestamps[container_id] = now
        return result
    except Exception as e:
        print(f"Error fetching stats for {container_id}: {e}")
        return None


def list_containers(include_stats=True):
    """List all Docker containers with their status."""
    service = _extension("container_inventory_service")
    if service is None:
        service = _default_container_inventory_service(DockerClientAdapter(docker_client))
    return service.list_containers(include_stats=include_stats)


def check_container_update(container):
    """Check if an update is available for the container's image."""
    return _container_operations().check_update(container)


def update_container(container):
    """Pull the latest image and recreate the service using docker compose."""
    return _container_operations().update(container)


def get_container_logs(container_id, tail=200):
    """Return the recent logs for a container."""
    return _container_operations().logs(container_id, tail=tail)


def socket_probe(host="8.8.8.8", port=53, timeout=5):
    """Attempt a TCP socket connection as a fallback network check."""
    return execute_socket_probe(socket.create_connection, host, port, timeout)


def run_network_test():
    """Ping 8.8.8.8 and report local/public IP details."""
    return _network_diagnostics().host_test()


def run_container_fallback_probe(container):
    """Try alternative connectivity checks inside a container."""
    return execute_container_fallback_probe(container, executor=exec_in_container)


def get_container_local_ip(container):
    """Retrieve the container's local IP address if possible."""
    return read_container_local_ip(container, executor=exec_in_container)


def get_container_public_ip(container):
    """Try to fetch the container's public IP using available tools."""
    return read_container_public_ip(container, executor=exec_in_container)


def run_container_network_test(container_id):
    """Run a network diagnostic from inside a specific container."""
    try:
        return _network_diagnostics().container_test(container_id)
    except DockerUnavailableError as exc:
        return {"error": str(exc)}


def get_host_public_ip():
    """Return the host's public IP, or None if it can't be determined."""
    try:
        with urlrequest.urlopen("https://api.ipify.org", timeout=10) as response:
            return response.read().decode("utf-8").strip()
    except Exception:
        return None


def list_network_groups(probe=False):
    """Return VPN-style network groups: a provider container plus the containers
    sharing its namespace, with health and orphan status. When probe=True, also
    compare the provider's public IP against the host's to detect a VPN leak."""
    return _network_groups().list_groups(probe=probe)


def recreate_network_group(provider_name):
    """Recreate a provider and every container sharing its namespace together,
    via `docker compose up -d`, so they all re-bind to the same live namespace.

    This is the one-click remedy for the orphaned-namespace failure: doing the
    services individually (or `docker start`) re-pins them to the dead namespace."""
    try:
        return _network_groups().recreate(provider_name)
    except DockerUnavailableError:
        return {"error": "Docker is not available"}


def control_container(container_id, action):
    """Start, stop, or restart a container by ID."""
    return _container_operations().control(container_id, action)


def system_action(action):
    """Perform system actions like shutdown or reboot."""
    try:
        if action == "shutdown":
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
            return {"status": "Shutdown initiated"}
        elif action == "reboot":
            subprocess.Popen(['sudo', 'reboot'])
            return {"status": "Reboot initiated"}
        else:
            return {"error": "Invalid system action"}
    except Exception as e:
        return {"error": str(e)}


_LEGACY_PAGE_REDIRECTS = {
    'system': '/v2/system',
    'containers': '/v2/containers',
    'apps': '/v2/apps',
    'stacks': '/v2/stacks',
    'tools': '/v2/apps',
    'settings': '/v2/settings',
    'storage': '/v2/plugins',
    'pools': '/v2/pools',
    'mounts': '/v2/mounts',
    'shares': '/v2/shares',
    'plugins': '/v2/plugins',
    'disks': '/v2/disks',
    'network': '/v2/network',
    'tailscale': '/v2/network',
}


@core_api.route('/')
def serve_frontend():
    """Serve the v2 SPA at the canonical root URL."""
    return serve_v2_index()


@core_api.route('/<page>.html')
def redirect_legacy_page(page):
    """Redirect allowlisted legacy bookmarks to their v2 destination."""
    target = _LEGACY_PAGE_REDIRECTS.get(page)
    if target is None:
        return jsonify({'error': f'legacy page not found: {page}'}), 404
    return redirect(target)


@core_api.route('/login.html')
def serve_login():
    """Serve the login page."""
    return send_from_directory(current_app.static_folder, 'login.html')


def get_v2_static_dir():
    """Return the absolute static directory used for v2 build artifacts."""
    return os.path.join(current_app.static_folder, 'v2')


def v2_index_exists():
    """Return True when the published v2 index artifact exists."""
    return os.path.isfile(os.path.join(get_v2_static_dir(), 'index.html'))


@core_api.route('/v2')
@core_api.route('/v2/')
def serve_v2_index():
    """Serve the v2 SPA entrypoint."""
    if not v2_index_exists():
        return jsonify({
            "error": "v2 build artifacts are missing",
            "hint": "run `npm --prefix frontend run build:publish`",
        }), 404
    return send_from_directory(get_v2_static_dir(), 'index.html')


@core_api.route('/v2/<path:path>')
def serve_v2_path(path):
    """Serve v2 assets directly and fallback route-like paths to SPA index."""
    v2_static_dir = get_v2_static_dir()
    resolved_path = safe_join(v2_static_dir, path)
    if resolved_path and os.path.isfile(resolved_path):
        return send_from_directory(v2_static_dir, path)

    first_segment = path.split('/', 1)[0]
    has_extension = os.path.splitext(path)[1] != ''
    is_asset_request = first_segment == 'assets' or has_extension

    # Missing assets must return 404 instead of falling back to index.html.
    if is_asset_request:
        return jsonify({"error": f"v2 asset not found: {path}"}), 404

    if not v2_index_exists():
        return jsonify({
            "error": "v2 build artifacts are missing",
            "hint": "run `npm --prefix frontend run build:publish`",
        }), 404

    return send_from_directory(v2_static_dir, 'index.html')


def _env_flag(name):
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _login_client_key():
    """Client identity for login rate limiting.

    When ``TRUSTED_PROXY`` is enabled, uses the right-most ``X-Forwarded-For``
    hop — the address the trusted proxy itself appended. The left-most hops are
    client-supplied, so keying on them would let an attacker mint a fresh
    rate-limit bucket per request by rotating a fake header value.
    """
    if current_app.config.get("TRUSTED_PROXY"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return request.remote_addr or "unknown"


def _capability_identity(username):
    authorizer = _extension("capability_authorizer")
    if authorizer is None:
        return {"role": None, "permissions": []}
    try:
        role = authorizer.role_for(username)
        permissions = tuple(authorizer.permissions_for(username))
        return {
            "role": role if isinstance(role, str) else None,
            "permissions": sorted(
                permission
                for permission in permissions
                if permission in CAPABILITY_PERMISSIONS
            ),
        }
    except Exception:
        return {"role": None, "permissions": []}


@core_api.route('/api/login', methods=['POST'])
def api_login():
    """API endpoint for user authentication."""
    client_key = _login_client_key()
    retry_after = _login_rate_limiter().retry_after(client_key)
    if retry_after:
        response = jsonify({'error': 'Too many login attempts. Try again later.'})
        response.headers['Retry-After'] = str(retry_after)
        return response, 429

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if verify_credentials(username, password):
        _login_rate_limiter().reset(client_key)
        session['authenticated'] = True
        session['username'] = username
        return jsonify({
            'status': 'success',
            'username': username,
            'csrf_token': rotate_csrf_token(),
            **_capability_identity(username),
        })
    else:
        retry_after = _login_rate_limiter().record_failure(client_key)
        if retry_after:
            response = jsonify({'error': 'Too many login attempts. Try again later.'})
            response.headers['Retry-After'] = str(retry_after)
            return response, 429
        return jsonify({'error': 'Invalid credentials'}), 401


@core_api.route('/api/logout', methods=['POST'])
def api_logout():
    """API endpoint for user logout."""
    session.clear()
    return jsonify({'status': 'logged out'})


@core_api.route('/api/auth/check', methods=['GET'])
def api_auth_check():
    """API endpoint to check authentication status."""
    if session.get('authenticated'):
        username = session.get('username', 'unknown')
        return jsonify({
            'authenticated': True,
            'username': username,
            'csrf_token': get_csrf_token(),
            **_capability_identity(username),
        })
    return jsonify({'authenticated': False}), 401


@core_api.route('/js/<path:path>')
def serve_js(path):
    return send_from_directory(os.path.join(current_app.static_folder, 'js'), path)

@core_api.route('/css/<path:path>')
def serve_css(path):
    return send_from_directory(os.path.join(current_app.static_folder, 'css'), path)

@core_api.route('/favicon.svg')
def serve_favicon():
    return send_from_directory(current_app.static_folder, 'favicon.svg')

@core_api.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    """API endpoint to return system stats as JSON."""
    return jsonify(current_app.extensions["system_service"].stats())


@core_api.route('/api/overview', methods=['GET'])
@login_required
def api_overview():
    """Return one bounded, partial-failure-safe Overview snapshot."""
    return jsonify(current_app.extensions["overview_service"].snapshot())


@core_api.route('/api/system/history', methods=['GET'])
@login_required
def api_system_history():
    """Return bounded metric history for one fixed reporting range."""
    try:
        history = current_app.extensions["metric_history_service"].query(
            request.args.get("range", "24h")
        )
    except InvalidMetricRange as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(history)


@core_api.route('/api/containers', methods=['GET'])
@login_required
def api_list_containers():
    """API endpoint to list all Docker containers."""
    include_stats = request.args.get('stats', 'true').lower() != 'false'
    service = current_app.extensions["container_inventory_service"]
    return jsonify(service.list_containers(include_stats=include_stats))


@core_api.route('/api/containers/stats', methods=['GET'])
@login_required
def api_container_stats_batch():
    """API endpoint to fetch stats for multiple containers at once."""
    if not _docker_is_available():
        return jsonify({})

    ids = request.args.get('ids', '')
    container_ids = [cid.strip() for cid in ids.split(',') if cid.strip()]

    if not container_ids:
        return jsonify({})

    result = {}
    for container_id in container_ids:
        stats = get_container_stats_cached(container_id)
        if stats:
            result[container_id] = {
                'cpu_percent': stats.get('cpu_percent'),
                'memory_percent': stats.get('memory', {}).get('percent'),
                'memory_used': stats.get('memory', {}).get('used'),
                'memory_limit': stats.get('memory', {}).get('limit'),
                'net_rx': stats.get('network', {}).get('rx'),
                'net_tx': stats.get('network', {}).get('tx'),
            }
    return jsonify(result)


@core_api.route('/api/containers/<container_id>', methods=['GET'])
@login_required
def api_inspect_container(container_id):
    """Inspect a container. Pass ?env=full to return secret environment values."""
    include_env_values = request.args.get("env", "").lower() == "full"
    service = current_app.extensions["container_inventory_service"]
    try:
        return jsonify(
            service.inspect(container_id, include_env_values=include_env_values)
        )
    except ContainerInspectUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    except ContainerInspectNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ContainerInspectError as exc:
        return jsonify({"error": str(exc)}), 500


@core_api.route('/api/containers/<container_id>/<action>', methods=['POST'])
@login_required
def api_control_container(container_id, action):
    """API endpoint to control a Docker container."""
    service = current_app.extensions["container_operations_service"]
    return jsonify(service.control(container_id, action))


@core_api.route('/api/containers/<container_id>/logs', methods=['GET'])
@login_required
def api_container_logs(container_id):
    """API endpoint to fetch container logs."""
    tail = request.args.get('tail', default=200, type=int)
    service = current_app.extensions["container_operations_service"]
    return jsonify(service.logs(container_id, tail=tail))


@core_api.route('/api/shutdown', methods=['POST'])
@login_required
def api_shutdown():
    """API endpoint to shutdown the system."""
    return jsonify(system_action("shutdown"))


@core_api.route('/api/reboot', methods=['POST'])
@login_required
def api_reboot():
    """API endpoint to reboot the system."""
    return jsonify(system_action("reboot"))


@core_api.route('/api/network-test', methods=['POST'])
@login_required
def api_network_test():
    """API endpoint to run a network connectivity test."""
    service = current_app.extensions["network_diagnostics_service"]
    return jsonify(service.host_test())


@core_api.route('/api/containers/<container_id>/network-test', methods=['POST'])
@login_required
def api_container_network_test(container_id):
    """API endpoint to run a network test from inside a specific container."""
    service = current_app.extensions["network_diagnostics_service"]
    try:
        return jsonify(service.container_test(container_id))
    except DockerUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503


@core_api.route('/api/containers/<container_id>/health', methods=['GET'])
@login_required
def api_container_health(container_id):
    """API endpoint to fetch a container's healthcheck status and latest output."""
    service = current_app.extensions["network_diagnostics_service"]
    try:
        return jsonify(service.health(container_id))
    except DockerUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    except ContainerNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@core_api.route('/api/network-groups', methods=['GET'])
@login_required
def api_network_groups():
    """API endpoint listing shared-network (VPN) groups, their members, and orphans.

    Pass ?probe=true to also compare provider vs host public IP (VPN leak check)."""
    probe = request.args.get('probe', 'false').lower() == 'true'
    service = current_app.extensions["network_group_service"]
    return jsonify(service.list_groups(probe=probe))


@core_api.route('/api/network-groups/<provider>/recreate', methods=['POST'])
@login_required
def api_recreate_network_group(provider):
    """API endpoint to recreate a provider and its namespace-sharing members together."""
    service = current_app.extensions["network_group_service"]
    try:
        return jsonify(service.recreate(provider))
    except DockerUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503


def _media_layout_service():
    return current_app.extensions["media_layout_service"]


def _media_seed_service():
    return current_app.extensions["media_seed_service"]


def _media_profile_service():
    return current_app.extensions["media_profile_service"]


def _media_quickstart_service():
    return current_app.extensions["media_quickstart_service"]


@core_api.route('/api/media/layout', methods=['GET'])
@login_required
def api_media_layout():
    """Return the canonical media layout roots and derived directories."""
    layout = _media_layout_service().layout()
    return jsonify({
        "layout": layout.as_dict(),
        "libraries": {
            kind: layout.library_path(kind)
            for kind in LIBRARY_KINDS
        },
        "downloads": {
            "incomplete": layout.download_incomplete_path(),
            "complete": {
                category: layout.download_complete_path(category)
                for category in DOWNLOAD_CATEGORIES
            },
        },
    })


@core_api.route('/api/media/layout', methods=['POST'])
@login_required
@csrf_protect
def api_media_layout_save():
    """Persist canonical media layout roots."""
    try:
        layout = _media_layout_service().save(request.get_json() or {})
    except MediaLayoutValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "saved", "layout": layout.as_dict()})


@core_api.route('/api/media/layout/provision', methods=['POST'])
@login_required
@csrf_protect
def api_media_layout_provision():
    """Create canonical library/download folders through the helper."""
    data = request.get_json() or {}
    try:
        result = _media_layout_service().provision(
            puid=data.get("puid", "1000"),
            pgid=data.get("pgid", "1000"),
        )
    except MediaLayoutProvisionError as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify(result)


@core_api.route('/api/media/seed', methods=['POST'])
@login_required
@csrf_protect
def api_media_seed():
    """Start a streamed media seed operation."""
    data = request.get_json() or {}
    stack_name = str(data.get("stack") or "media")
    from stack_manager import validate_stack_name

    valid, error = validate_stack_name(stack_name)
    if not valid:
        return jsonify({"error": error}), 400

    def produce_events():
        yield from _media_seed_service().seed_stack(stack_name)

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session['csrf_token'],
            username=session.get('username', 'unknown'),
            kind='media_seed',
            target=stack_name,
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({'error': str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({'error': f'Unable to start media seed: {exc}'}), 500

    return jsonify({
        'operation_id': operation.operation_id,
        'stream_url': f'/api/media/seed/operations/{operation.operation_id}/stream',
    }), 202


@core_api.route('/api/media/seed/operations/<operation_id>/stream', methods=['GET'])
@login_required
def api_stream_media_seed(operation_id):
    """Replay and follow one media seed operation."""
    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind='media_seed',
    )


@core_api.route('/api/media/quickstart', methods=['POST'])
@login_required
@csrf_protect
def api_media_quickstart():
    """Start the one-shot media stack quickstart operation."""
    data = request.get_json() or {}
    stack_name = str(data.get("stack") or "media")
    from stack_manager import validate_stack_name

    valid, error = validate_stack_name(stack_name)
    if not valid:
        return jsonify({"error": error}), 400

    values = data.get("values", {})
    if not isinstance(values, dict):
        return jsonify({"error": "values must be an object"}), 400

    username = session.get('username', 'unknown')

    def produce_events():
        yield from _media_quickstart_service().stream_quickstart(
            stack_name=stack_name,
            values=values,
            username=username,
        )

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session['csrf_token'],
            username=username,
            kind='media_quickstart',
            target=stack_name,
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({'error': str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({'error': f'Unable to start media quickstart: {exc}'}), 500

    return jsonify({
        'operation_id': operation.operation_id,
        'stream_url': f'/api/media/quickstart/operations/{operation.operation_id}/stream',
    }), 202


@core_api.route('/api/media/quickstart/operations/<operation_id>/stream', methods=['GET'])
@login_required
def api_stream_media_quickstart(operation_id):
    """Replay and follow one media quickstart operation."""
    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind='media_quickstart',
    )


@core_api.route('/api/pihealth/update/config', methods=['GET'])
@login_required
def api_pihealth_update_config():
    return jsonify(_load_pihealth_update_config())


@core_api.route('/api/pihealth/update/config', methods=['POST'])
@login_required
def api_pihealth_update_config_save():
    data = request.get_json() or {}
    repo_path = str(data.get("repo_path", "")).strip()
    service_name = str(data.get("service_name", "")).strip()

    if not repo_path or not repo_path.startswith("/"):
        return jsonify({"error": "repo_path must be absolute"}), 400
    if not service_name:
        return jsonify({"error": "service_name is required"}), 400

    config = {"repo_path": repo_path, "service_name": service_name}
    _save_pihealth_update_config(config)
    return jsonify({"status": "saved", "config": config})


@core_api.route('/api/health', methods=['GET'])
def api_health():
    """Unauthenticated liveness probe used to detect recovery after a restart."""
    return jsonify({"status": "ok"})


@core_api.route('/api/pihealth/update', methods=['POST'])
@login_required
@csrf_protect
def api_pihealth_update():
    """Start a streamed self-update and return its read-only event stream."""
    config = _load_pihealth_update_config()
    config["user"] = getpass.getuser()

    def produce_events():
        yield from stream_pihealth_update(helper_call, config)

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session['csrf_token'],
            username=session.get('username', 'unknown'),
            kind='pihealth_update',
            target='pi-health',
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({'error': str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({'error': f'Unable to start update: {exc}'}), 500

    return jsonify({
        'operation_id': operation.operation_id,
        'stream_url': f'/api/pihealth/update/operations/{operation.operation_id}/stream',
    }), 202


@core_api.route('/api/pihealth/update/operations/<operation_id>/stream', methods=['GET'])
@login_required
def api_stream_pihealth_update(operation_id):
    """Replay and follow one previously created self-update operation."""
    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind='pihealth_update',
    )


SECRET_KEY_FILE = RUNTIME_CONFIG_DIR / "secret_key"


def _load_or_create_secret_key():
    """Return a persisted Flask secret key, creating one on first run.

    Persisting the key keeps sessions and CSRF tokens valid across restarts,
    including the in-app self-update (which restarts the service). Falls back to an
    ephemeral key only if the file cannot be written (e.g. a read-only runtime dir).
    """
    try:
        existing = SECRET_KEY_FILE.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass

    key = secrets.token_hex(32)
    try:
        SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL so concurrent workers don't clobber each other's key.
        fd = os.open(SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(key)
        return key
    except FileExistsError:
        try:
            return SECRET_KEY_FILE.read_text().strip() or key
        except OSError:
            return key
    except OSError:
        return key


def _resolve_secret_key():
    return os.getenv("SECRET_KEY") or _load_or_create_secret_key()


def create_app(config=None, dependencies=None):
    """Build an isolated LimeOS web application."""
    config = dict(config or {})
    static_folder = config.pop("STATIC_FOLDER", "static")
    application = Flask(__name__, static_folder=static_folder)
    application.config.from_mapping(
        CAPABILITY_USER_ROLES=None,
        INIT_PLUGINS=True,
        LIMEOS_VERSION="0.1.0",
        START_SCHEDULERS=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        TRUSTED_PROXY=_env_flag("PIHEALTH_TRUSTED_PROXY"),
    )
    application.config.update(config)
    if not application.config.get("SECRET_KEY"):
        application.config["SECRET_KEY"] = _resolve_secret_key()

    @application.before_request
    def _enforce_csrf():
        """Require a valid CSRF token for authenticated state-changing requests."""
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if request.path == "/api/login":
            return None  # Login mints the token; it cannot require one yet.
        if not session.get("authenticated"):
            return None  # Unauthenticated mutations are rejected by login_required (401).
        expected = session.get("csrf_token")
        provided = request.headers.get("X-CSRF-Token", "")
        if (
            not isinstance(expected, str)
            or not isinstance(provided, str)
            or not hmac.compare_digest(expected, provided)
        ):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return None

    resolved = dependencies or _default_dependencies()
    application.extensions["auth_users"] = dict(resolved.users)
    application.extensions["login_rate_limiter"] = resolved.login_rate_limiter
    application.extensions["docker_client"] = resolved.docker_client
    application.extensions["operation_registry"] = (
        resolved.operation_registry or OperationRegistry(clock=resolved.clock)
    )
    application.extensions["clock"] = resolved.clock
    application.extensions["helper"] = resolved.helper or HelperClientAdapter()
    application.extensions["docker"] = resolved.docker or DockerClientAdapter(resolved.docker_client)
    application.extensions["scheduler"] = resolved.scheduler
    application.extensions["audit"] = resolved.audit or FileAuditWriter()
    application.extensions["config_repo"] = resolved.config_repo or JsonFileRepository()
    application.extensions["system_service"] = (
        resolved.system_service or _default_system_service()
    )
    application.extensions["container_inventory_service"] = (
        resolved.container_inventory_service
        or _default_container_inventory_service(application.extensions["docker"])
    )
    application.extensions["container_operations_service"] = (
        resolved.container_operations_service
        or _default_container_operations_service(application.extensions["docker"])
    )
    application.extensions["network_diagnostics_service"] = (
        resolved.network_diagnostics_service
        or _default_network_diagnostics_service(application.extensions["docker"])
    )
    application.extensions["network_group_service"] = (
        resolved.network_group_service
        or _default_network_group_service(application.extensions["docker"])
    )
    application.extensions["stack_read_service"] = (
        resolved.stack_read_service or default_stack_read_service()
    )
    application.extensions["stack_mutation_service"] = (
        resolved.stack_mutation_service or default_stack_mutation_service()
    )
    application.extensions["stack_operations_service"] = (
        resolved.stack_operations_service or default_stack_operations_service()
    )
    application.extensions["disk_inventory_service"] = (
        resolved.disk_inventory_service or default_disk_inventory_service()
    )
    application.extensions["disk_mount_service"] = (
        resolved.disk_mount_service
        or default_disk_mount_service(application.extensions["helper"], resolved.docker_client)
    )
    application.extensions["media_paths_service"] = (
        resolved.media_paths_service
        or default_media_paths_service(
            application.extensions["helper"], application.extensions["config_repo"]
        )
    )
    application.extensions["media_layout_service"] = (
        resolved.media_layout_service
        or _default_media_layout_service(
            application.extensions["helper"], application.extensions["config_repo"]
        )
    )
    application.extensions["media_profile_service"] = (
        resolved.media_profile_service
        or _default_media_profile_service(application.extensions["config_repo"])
    )
    application.extensions["media_seed_service"] = (
        resolved.media_seed_service
        or _default_media_seed_service(application.extensions["media_layout_service"])
    )
    application.extensions["seedbox_service"] = (
        resolved.seedbox_service
        or default_seedbox_service(
            application.extensions["helper"], application.extensions["config_repo"]
        )
    )
    application.extensions["disk_suggestion_service"] = (
        resolved.disk_suggestion_service
        or default_disk_suggestion_service(
            application.extensions["disk_inventory_service"]
        )
    )
    application.extensions["smart_service"] = (
        resolved.smart_service or default_smart_service(application.extensions["helper"])
    )
    application.extensions["disk_summary_service"] = (
        resolved.disk_summary_service
        or default_disk_summary_service(
            application.extensions["disk_inventory_service"],
            application.extensions["smart_service"],
        )
    )
    application.extensions["storage_read_service"] = (
        resolved.storage_read_service or default_storage_read_service()
    )
    application.extensions["update_service"] = (
        resolved.update_service
        or default_update_service(application.extensions["config_repo"])
    )
    application.extensions["backup_service"] = (
        resolved.backup_service
        or default_backup_service(application.extensions["config_repo"])
    )
    application.extensions["catalog_service"] = (
        resolved.catalog_service or default_catalog_service()
    )
    application.extensions["media_quickstart_service"] = (
        resolved.media_quickstart_service
        or _default_media_quickstart_service(
            application.extensions["media_layout_service"],
            application.extensions["catalog_service"],
            application.extensions["stack_operations_service"],
            application.extensions["media_seed_service"],
            application.extensions["media_profile_service"],
        )
    )
    application.extensions["tools_service"] = (
        resolved.tools_service
        or default_tools_service(application.extensions["config_repo"])
    )
    application.extensions["mattermost_integration_service"] = (
        resolved.mattermost_integration_service
        or _default_mattermost_integration_service(
            application.extensions["config_repo"], application.extensions["docker"]
        )
    )
    application.extensions["stack_notifications_service"] = (
        resolved.stack_notifications_service
        or _default_stack_notifications_service(application.extensions["config_repo"])
    )
    application.extensions["agent_integration_service"] = (
        resolved.agent_integration_service
        or _default_agent_integration_service(
            application.extensions["mattermost_integration_service"],
            application.extensions["docker"],
            application.extensions["stack_read_service"],
        )
    )
    application.extensions["overview_service"] = (
        resolved.overview_service
        or _default_overview_service(
            application.extensions["system_service"],
            application.extensions["container_inventory_service"],
            application.extensions["stack_read_service"],
            application.extensions["mattermost_integration_service"],
        )
    )
    application.extensions["metric_history_service"] = (
        resolved.metric_history_service or _default_metric_history_service()
    )
    application.extensions["capability_registry_service"] = (
        resolved.capability_registry_service
        or _default_capability_registry_service(application)
    )
    application.extensions["capability_authorizer"] = (
        resolved.capability_authorizer
        or CapabilityAuthorizer(
            resolve_capability_roles(
                resolved.users,
                application.config.get("CAPABILITY_USER_ROLES")
                if application.config.get("CAPABILITY_USER_ROLES") is not None
                else resolved.capability_roles,
            )
        )
    )
    application.extensions["capability_lifecycle_service"] = (
        resolved.capability_lifecycle_service or ExtensionLifecycleService()
    )

    application.register_blueprint(core_api)
    application.register_blueprint(stack_manager)
    application.register_blueprint(catalog_manager)
    application.register_blueprint(tools_manager)
    application.register_blueprint(integrations_manager)
    application.register_blueprint(storage_bp)
    application.register_blueprint(update_scheduler)
    application.register_blueprint(backup_scheduler)
    application.register_blueprint(disk_manager)
    application.register_blueprint(setup_manager)
    application.register_blueprint(capability_api)

    if application.config["INIT_PLUGINS"]:
        init_plugins(STORAGE_PLUGIN_CONFIG_DIR)
    if application.config["START_SCHEDULERS"]:
        init_scheduler(application)
        init_backup_scheduler(application)
        _start_agent_convergence()

    print(f"Loaded {len(resolved.users)} user(s) for authentication")
    return application


def _start_agent_convergence():
    """Converge a stale agent runtime after a self-update restart, in the background.

    A self-update runs the pre-pull orchestrator/helper, so the release that first ships
    an agent-runtime change cannot converge it in that same flow. Once the web service has
    restarted on the new code it asks the helper to converge if the deployed commit is
    behind — closing the bootstrap gap without a second update. Best-effort: it never
    blocks or fails web startup.
    """
    import threading

    def _run():
        try:
            from helper_client import helper_call
            helper_call("agent_converge_if_stale", {})
        except Exception:
            pass

    threading.Thread(target=_run, name="agent-convergence", daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    create_app().run(host="0.0.0.0", port=port)
