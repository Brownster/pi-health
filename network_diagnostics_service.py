"""Framework-neutral host and container network diagnostics."""

from __future__ import annotations

import subprocess

from ports import DockerPort


class DockerUnavailableError(RuntimeError):
    """Raised when a diagnostic requires Docker but no client is available."""


class ContainerNotFoundError(RuntimeError):
    """Raised when health details cannot resolve the requested container."""


def socket_probe(socket_connector, host="8.8.8.8", port=53, timeout=5):
    try:
        with socket_connector((host, port), timeout=timeout):
            return True, f"Socket connection to {host}:{port} succeeded."
    except OSError as exc:
        return False, f"Socket connection to {host}:{port} failed: {exc}"


def run_host_network_test(*, command_runner, socket_connector, urlopen) -> dict:
    ping_output = ""
    ping_success = False
    probe_method = "ping"
    try:
        result = command_runner(
            ["ping", "-c", "4", "8.8.8.8"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        ping_output = result.stdout or result.stderr or ""
        ping_success = result.returncode == 0
    except FileNotFoundError:
        probe_method = "socket"
        ping_success, message = socket_probe(socket_connector)
        ping_output = "Ping command not available in this container.\n" + message
    except subprocess.TimeoutExpired as exc:
        ping_output = exc.stdout or exc.stderr or "Ping timed out."
    except Exception as exc:
        ping_output = str(exc)

    local_ip = None
    try:
        result = command_runner(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        local_ip = result.stdout.strip() or result.stderr.strip()
    except Exception:
        pass

    public_ip = None
    try:
        with urlopen("https://api.ipify.org", timeout=10) as response:
            public_ip = response.read().decode("utf-8").strip()
    except Exception:
        pass

    return {
        "ping_success": ping_success,
        "ping_output": ping_output,
        "local_ip": local_ip,
        "public_ip": public_ip,
        "probe_method": probe_method,
    }


def command_missing(exit_code, output):
    output = (output or "").lower()
    return exit_code in (126, 127) or "not found" in output or "no such file" in output


def exec_in_container(container, script):
    try:
        result = container.exec_run(
            ["/bin/sh", "-c", script], stdout=True, stderr=True
        )
    except FileNotFoundError:
        result = container.exec_run(["sh", "-c", script], stdout=True, stderr=True)

    output = result.output
    if isinstance(output, tuple):
        stdout, stderr = output
        decoded = ""
        if stdout:
            decoded += stdout.decode("utf-8", errors="replace")
        if stderr:
            decoded += stderr.decode("utf-8", errors="replace")
        output_text = decoded
    elif isinstance(output, (bytes, bytearray)):
        output_text = output.decode("utf-8", errors="replace")
    else:
        output_text = str(output)
    return result.exit_code, output_text.strip()


def container_http_probe_script(tool_name):
    commands = {
        "curl": "curl -s --max-time 10 https://api.ipify.org",
        "wget": "wget -qO- --timeout=10 https://api.ipify.org",
        "busybox": "busybox wget -qO- https://api.ipify.org",
    }
    if tool_name == "python3":
        python_script = (
            "python3 - <<'PY'\n"
            "import socket\n"
            "sock = socket.create_connection(('8.8.8.8', 53), timeout=5)\n"
            "print('Socket connection to 8.8.8.8:53 succeeded')\n"
            "sock.close()\n"
            "PY"
        )
        return (
            "if command -v python3 >/dev/null 2>&1; then\n"
            f"{python_script}\n"
            "else\n"
            "  exit 127\n"
            "fi"
        )
    tool_command = commands.get(tool_name, "")
    if not tool_command:
        return "exit 127"
    return (
        f"if command -v {tool_name} >/dev/null 2>&1; then\n"
        f"  {tool_command}\n"
        "else\n"
        "  exit 127\n"
        "fi"
    )


def run_container_fallback_probe(container, *, executor=exec_in_container):
    probes = [("curl", True), ("wget", True), ("busybox", True), ("python3", False)]
    for tool, provides_public_ip in probes:
        exit_code, output = executor(container, container_http_probe_script(tool))
        if exit_code == 0:
            message = f"{tool} connectivity test succeeded."
            if output:
                message += f"\n{output}"
            public_ip = output.strip() if provides_public_ip and output else None
            return True, message, tool, public_ip
        if command_missing(exit_code, output):
            continue
        return False, output or f"{tool} connectivity test failed", tool, None
    return (
        False,
        "No available networking tools (ping/curl/wget/python3) inside the container.",
        "unavailable",
        None,
    )


def get_container_local_ip(container, *, executor=exec_in_container):
    exit_code, output = executor(container, "hostname -I 2>/dev/null")
    return output.strip() if exit_code == 0 and output else None


def get_container_public_ip(container, *, executor=exec_in_container):
    script = (
        "if command -v curl >/dev/null 2>&1; then\n"
        "  curl -s --max-time 10 https://api.ipify.org\n"
        "elif command -v wget >/dev/null 2>&1; then\n"
        "  wget -qO- --timeout=10 https://api.ipify.org\n"
        "elif command -v busybox >/dev/null 2>&1; then\n"
        "  busybox wget -qO- https://api.ipify.org\n"
        "else\n"
        "  exit 127\n"
        "fi"
    )
    exit_code, output = executor(container, script)
    return output.strip() if exit_code == 0 and output else None


def run_container_network_test(container, *, executor=exec_in_container) -> dict:
    ping_success = False
    ping_output = ""
    probe_method = "ping"
    fallback_public_ip = None
    try:
        exit_code, output = executor(container, "ping -c 4 8.8.8.8")
        ping_output = output
        if exit_code == 0:
            ping_success = True
        elif command_missing(exit_code, output):
            ping_success, message, tool, fallback_public_ip = run_container_fallback_probe(
                container, executor=executor
            )
            ping_output = ((ping_output + "\n\n") if ping_output else "") + message
            probe_method = tool if ping_success else f"{tool}-failed"
    except Exception as exc:
        ping_output = str(exc)

    local_ip = get_container_local_ip(container, executor=executor)
    public_ip = get_container_public_ip(container, executor=executor)
    if fallback_public_ip:
        public_ip = fallback_public_ip
    return {
        "container_id": container.id,
        "container_name": container.name,
        "ping_success": ping_success,
        "ping_output": ping_output,
        "local_ip": local_ip,
        "public_ip": public_ip,
        "probe_method": probe_method,
    }


def get_container_health(container):
    try:
        return ((container.attrs.get("State") or {}).get("Health") or {}).get("Status")
    except Exception:
        return None


def get_container_health_detail(container):
    state = container.attrs.get("State") or {}
    health = state.get("Health") or {}
    log = health.get("Log") or []
    last_output = None
    if log:
        output = (log[-1].get("Output") or "").strip()
        last_output = output[-500:] if output else None
    return {
        "status": health.get("Status"),
        "failing_streak": health.get("FailingStreak"),
        "last_output": last_output,
    }


class NetworkDiagnosticsService:
    def __init__(self, *, docker: DockerPort, command_runner, socket_connector, urlopen):
        self._docker = docker
        self._command_runner = command_runner
        self._socket_connector = socket_connector
        self._urlopen = urlopen

    def host_test(self) -> dict:
        return run_host_network_test(
            command_runner=self._command_runner,
            socket_connector=self._socket_connector,
            urlopen=self._urlopen,
        )

    def container_test(self, container_id: str) -> dict:
        if not self._docker.available:
            raise DockerUnavailableError("Docker is not available")
        try:
            container = self._docker.get_container(container_id)
        except Exception as exc:
            return {"error": str(exc)}
        return run_container_network_test(container)

    def health(self, container_id: str) -> dict:
        if not self._docker.available:
            raise DockerUnavailableError("Docker is not available")
        try:
            container = self._docker.get_container(container_id)
        except Exception as exc:
            raise ContainerNotFoundError(str(exc)) from exc
        return get_container_health_detail(container)
