"""Pure Docker container metadata and calculation helpers."""

import os
from urllib.parse import urlsplit


def parse_port_key(port_key):
    """Split Docker's port key (e.g. '8080/tcp') into structured parts."""
    if not port_key:
        return None, None
    if isinstance(port_key, int):
        return port_key, 'tcp'

    try:
        port_str, protocol = port_key.split('/')
    except ValueError:
        port_str, protocol = port_key, 'tcp'

    try:
        port_num = int(port_str)
    except ValueError:
        port_num = None

    return port_num, protocol


def get_container_ports(container):
    """Return a structured list of ports exposed/published by a container."""
    ports = []
    seen_ports = set()

    try:
        network_settings = container.attrs.get('NetworkSettings', {})
        port_bindings = network_settings.get('Ports') or {}
        config = container.attrs.get('Config', {})
        exposed_ports = config.get('ExposedPorts') or {}
    except Exception as exc:
        print(f"Error inspecting ports for container {container.name}: {exc}")
        return ports

    for container_port, bindings in port_bindings.items():
        port_num, protocol = parse_port_key(container_port)
        seen_ports.add((port_num, protocol))

        if not bindings:
            ports.append({
                "container_port": port_num,
                "protocol": protocol,
                "host_port": None,
                "host_ip": None,
            })
            continue

        for binding in bindings:
            host_port = binding.get("HostPort")
            host_ip = binding.get("HostIp") or None
            ports.append({
                "container_port": port_num,
                "protocol": protocol,
                "host_port": int(host_port) if host_port else None,
                "host_ip": host_ip if host_ip not in ("0.0.0.0", "") else None,
            })

    for container_port in exposed_ports:
        port_num, protocol = parse_port_key(container_port)
        if (port_num, protocol) in seen_ports:
            continue
        ports.append({
            "container_port": port_num,
            "protocol": protocol,
            "host_port": None,
            "host_ip": None,
        })

    return ports


def get_container_web_metadata(container):
    """Return validated explicit service-link metadata for one container."""
    try:
        labels = (container.attrs.get('Config') or {}).get('Labels') or {}
    except Exception:
        labels = {}
    if not isinstance(labels, dict):
        labels = {}

    explicit_url = str(labels.get('limeos.web.url') or '').strip()
    if explicit_url and not any(ord(char) < 32 for char in explicit_url):
        try:
            parsed = urlsplit(explicit_url)
            scheme = parsed.scheme.lower()
            if (
                scheme in {'http', 'https'}
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
            ):
                return {'web_url': explicit_url, 'web_scheme': scheme}
        except ValueError:
            pass

    for candidate in (
        labels.get('limeos.web.scheme'),
        os.getenv('PIHEALTH_SERVICE_LINK_SCHEME'),
    ):
        scheme = str(candidate or '').strip().lower()
        if scheme in {'http', 'https'}:
            return {'web_url': None, 'web_scheme': scheme}

    return {'web_url': None, 'web_scheme': None}


def get_container_ports_cached(container, port_cache):
    """Return cached port metadata for a container to avoid repeated inspections."""
    if container.id not in port_cache:
        port_cache[container.id] = get_container_ports(container)
    return port_cache[container.id]


def inherit_ports_from_network_service(
    container,
    containers_by_name,
    port_cache,
    *,
    container_lookup=None,
):
    """Inherit host bindings when a container shares a Compose service network."""
    network_mode = (container.attrs.get("HostConfig") or {}).get("NetworkMode") or ""
    if not network_mode.startswith("service:"):
        return []

    service_name = network_mode.split(":", 1)[1]
    if not service_name:
        return []
    service_container = containers_by_name.get(service_name)
    if service_container is None and container_lookup is not None:
        try:
            service_container = container_lookup(service_name)
        except Exception:
            return []
    if service_container is None:
        return []

    service_ports = get_container_ports_cached(service_container, port_cache)
    exposed_ports = (container.attrs.get("Config") or {}).get("ExposedPorts") or {}
    if not service_ports or not exposed_ports:
        return []

    service_port_map = {}
    for port in service_ports:
        key = (port.get("container_port"), port.get("protocol"))
        service_port_map.setdefault(key, []).append(port)

    inherited = []
    for exposed_port in exposed_ports:
        port_num, protocol = parse_port_key(exposed_port)
        if port_num is None:
            continue
        matches = service_port_map.get((port_num, protocol))
        if not matches and protocol != "tcp":
            matches = service_port_map.get((port_num, "tcp"))
        if not matches:
            matches = service_port_map.get((port_num, None))
        if matches:
            for match in matches:
                inherited.append(
                    {
                        "container_port": port_num,
                        "protocol": protocol or match.get("protocol") or "tcp",
                        "host_port": match.get("host_port"),
                        "host_ip": match.get("host_ip"),
                        "via_service": service_name,
                    }
                )
        else:
            inherited.append(
                {
                    "container_port": port_num,
                    "protocol": protocol or "tcp",
                    "host_port": None,
                    "host_ip": None,
                    "via_service": service_name,
                }
            )
    return inherited


def calculate_container_cpu_percent(stats):
    """Calculate CPU percentage from Docker stats."""
    try:
        cpu_stats = stats.get('cpu_stats', {})
        precpu_stats = stats.get('precpu_stats', {})
        cpu_usage = cpu_stats.get('cpu_usage', {})
        precpu_usage = precpu_stats.get('cpu_usage', {})
        cpu_delta = cpu_usage.get('total_usage', 0) - precpu_usage.get('total_usage', 0)
        system_delta = cpu_stats.get('system_cpu_usage', 0) - precpu_stats.get('system_cpu_usage', 0)

        if system_delta > 0 and cpu_delta > 0:
            num_cpus = cpu_stats.get('online_cpus', 1) or len(cpu_usage.get('percpu_usage', [1]))
            return round((cpu_delta / system_delta) * num_cpus * 100.0, 1)
    except Exception:
        pass
    return None


def calculate_container_memory_stats(stats):
    """Extract memory usage stats from Docker stats."""
    try:
        memory_stats = stats.get('memory_stats', {})
        usage = memory_stats.get('usage', 0)
        limit = memory_stats.get('limit', 0)
        cache = memory_stats.get('stats', {}).get('cache', 0)
        actual_usage = usage - cache if cache else usage
        percent = round((actual_usage / limit) * 100, 1) if limit > 0 else None
        return {'used': actual_usage, 'limit': limit, 'percent': percent}
    except Exception:
        return {'used': None, 'limit': None, 'percent': None}


def calculate_container_network_stats(stats):
    """Sum network rx/tx bytes across all interfaces."""
    try:
        networks = stats.get('networks', {})
        return {
            'rx': sum(item.get('rx_bytes', 0) for item in networks.values()),
            'tx': sum(item.get('tx_bytes', 0) for item in networks.values()),
        }
    except Exception:
        return {'rx': None, 'tx': None}


def _network_target(host_config):
    mode = (host_config or {}).get('NetworkMode') or ''
    if mode.startswith('container:'):
        return 'container', mode.split(':', 1)[1]
    if mode.startswith('service:'):
        return 'service', mode.split(':', 1)[1]
    return None, None


def _compose_label(container, key):
    return ((container.attrs.get('Config') or {}).get('Labels') or {}).get(key)


def _compose_dependency_name(container):
    dep = _compose_label(container, 'com.docker.compose.depends_on') or ''
    first = dep.split(',')[0].strip()
    if first:
        return first.split(':', 1)[0].strip() or None
    return None


def analyze_network_topology(containers):
    """Describe shared network namespaces and identify orphaned members."""
    by_id = {container.id: container for container in containers}
    by_name = {container.name: container for container in containers}
    info = {}
    groups = {}

    for container in containers:
        host_config = container.attrs.get('HostConfig') or {}
        kind, value = _network_target(host_config)
        entry = {
            'mode': host_config.get('NetworkMode') or '',
            'role': 'standalone',
            'provider': None,
            'status': 'ok',
        }

        if kind in ('container', 'service'):
            entry['role'] = 'member'
            orphaned = False
            provider_name = None

            if kind == 'container':
                target = by_id.get(value)
                if target is None:
                    orphaned = True
                    provider_name = _compose_dependency_name(container)
                else:
                    provider_name = target.name
            else:
                provider_name = value
                if by_name.get(value) is None:
                    orphaned = True

            entry['provider'] = provider_name
            if orphaned:
                entry['status'] = 'orphaned'
            else:
                target = by_name.get(provider_name) if provider_name else None
                entry['status'] = (
                    'ok' if target is not None and getattr(target, 'status', None) == 'running'
                    else 'provider_stopped'
                )

            if provider_name:
                group = groups.setdefault(provider_name, {'members': set(), 'orphaned': set()})
                group['members'].add(container.name)
                if orphaned:
                    group['orphaned'].add(container.name)

        info[container.id] = entry

    for provider_name, group in groups.items():
        provider = by_name.get(provider_name)
        if provider is not None:
            provider_info = info.get(provider.id)
            if provider_info is not None:
                provider_info['role'] = 'provider'
                provider_info['provider'] = provider_name
                provider_info['members'] = sorted(group['members'])

    return info, groups
