import { requestApi, toNullableNumber, toNullableString } from "@/lib/api";

export type ContainerFilter = "all" | "running" | "stopped";
export type ContainerAction = "start" | "stop" | "restart" | "check_update" | "update";

export interface ContainerPortBinding {
  container_port: number | null;
  protocol: string | null;
  host_port: number | null;
  host_ip: string | null;
  via_service: string | null;
}

export interface ContainerSummary {
  id: string;
  name: string;
  status: string;
  image: string;
  update_available: boolean;
  ports: ContainerPortBinding[];
  cpu_percent: number | null;
  memory_percent: number | null;
  memory_used: number | null;
  memory_limit: number | null;
  net_rx: number | null;
  net_tx: number | null;
  web_url: string | null;
  web_scheme: "http" | "https" | null;
}

interface FetchContainersOptions {
  includeStats?: boolean;
  signal?: AbortSignal;
}

export interface ContainerActionResult {
  status?: string;
  error?: string;
  update_available?: boolean;
}

export interface ContainerLogsResult {
  logs: string;
  container: string | null;
}

export interface ContainerNetworkTestResult {
  ping_success: boolean;
  ping_output: string;
  local_ip: string | null;
  public_ip: string | null;
  probe_method: string | null;
  container_id: string | null;
  container_name: string | null;
}

export interface HostNetworkTestResult {
  ping_success: boolean;
  ping_output: string;
  local_ip: string | null;
  public_ip: string | null;
  probe_method: string | null;
}

export interface ContainerStatsSummary {
  cpu_percent: number | null;
  memory_percent: number | null;
  memory_used: number | null;
  memory_limit: number | null;
  net_rx: number | null;
  net_tx: number | null;
}

function normalizePortBinding(
  port: Partial<ContainerPortBinding> | undefined,
): ContainerPortBinding {
  if (!port) {
    return {
      container_port: null,
      protocol: null,
      host_port: null,
      host_ip: null,
      via_service: null,
    };
  }

  return {
    container_port: toNullableNumber(port.container_port),
    protocol: toNullableString(port.protocol),
    host_port: toNullableNumber(port.host_port),
    host_ip: toNullableString(port.host_ip),
    via_service: toNullableString(port.via_service),
  };
}

function normalizeContainer(
  container: Partial<ContainerSummary> | undefined,
): ContainerSummary {
  const id = String(container?.id ?? "");
  const webScheme = container?.web_scheme;
  return {
    id: id || "unknown-container",
    name: String(container?.name ?? "Unnamed"),
    status: String(container?.status ?? "unknown"),
    image: String(container?.image ?? "unknown"),
    update_available: Boolean(container?.update_available),
    ports: Array.isArray(container?.ports)
      ? container.ports.map((port) => normalizePortBinding(port))
      : [],
    cpu_percent: toNullableNumber(container?.cpu_percent),
    memory_percent: toNullableNumber(container?.memory_percent),
    memory_used: toNullableNumber(container?.memory_used),
    memory_limit: toNullableNumber(container?.memory_limit),
    net_rx: toNullableNumber(container?.net_rx),
    net_tx: toNullableNumber(container?.net_tx),
    web_url: toNullableString(container?.web_url),
    web_scheme: webScheme === "http" || webScheme === "https" ? webScheme : null,
  };
}

export async function fetchContainers(
  options: FetchContainersOptions = {},
): Promise<ContainerSummary[]> {
  const includeStats = options.includeStats ?? true;
  const payload = await requestApi<Partial<ContainerSummary>[]>(
    `/api/containers?stats=${includeStats ? "true" : "false"}`,
    {
      method: "GET",
      signal: options.signal,
    },
  );

  return payload.map((item) => normalizeContainer(item));
}

export async function runContainerAction(
  containerId: string,
  action: ContainerAction,
  signal?: AbortSignal,
): Promise<ContainerActionResult> {
  const payload = await requestApi<ContainerActionResult>(
    `/api/containers/${encodeURIComponent(containerId)}/${action}`,
    {
      method: "POST",
      signal,
    },
  );

  if (payload.error) {
    throw new Error(payload.error);
  }

  return payload;
}

export async function fetchContainerLogs(
  containerId: string,
  tail = 200,
  signal?: AbortSignal,
): Promise<ContainerLogsResult> {
  const payload = await requestApi<{
    logs?: string;
    container?: string;
    error?: string;
  }>(`/api/containers/${encodeURIComponent(containerId)}/logs?tail=${tail}`, {
    method: "GET",
    signal,
  });

  if (payload.error) {
    throw new Error(payload.error);
  }

  return {
    logs: payload.logs ?? "",
    container: toNullableString(payload.container),
  };
}

export async function runContainerNetworkTest(
  containerId: string,
  signal?: AbortSignal,
): Promise<ContainerNetworkTestResult> {
  const payload = await requestApi<{
    ping_success?: boolean;
    ping_output?: string;
    local_ip?: string;
    public_ip?: string;
    probe_method?: string;
    container_id?: string;
    container_name?: string;
    error?: string;
  }>(`/api/containers/${encodeURIComponent(containerId)}/network-test`, {
    method: "POST",
    signal,
  });

  if (payload.error) {
    throw new Error(payload.error);
  }

  return {
    ping_success: Boolean(payload.ping_success),
    ping_output: payload.ping_output ?? "",
    local_ip: toNullableString(payload.local_ip),
    public_ip: toNullableString(payload.public_ip),
    probe_method: toNullableString(payload.probe_method),
    container_id: toNullableString(payload.container_id),
    container_name: toNullableString(payload.container_name),
  };
}

export async function runHostNetworkTest(signal?: AbortSignal): Promise<HostNetworkTestResult> {
  const payload = await requestApi<{
    ping_success?: boolean;
    ping_output?: string;
    local_ip?: string;
    public_ip?: string;
    probe_method?: string;
    error?: string;
  }>("/api/network-test", {
    method: "POST",
    signal,
  });

  if (payload.error) {
    throw new Error(payload.error);
  }

  return {
    ping_success: Boolean(payload.ping_success),
    ping_output: payload.ping_output ?? "",
    local_ip: toNullableString(payload.local_ip),
    public_ip: toNullableString(payload.public_ip),
    probe_method: toNullableString(payload.probe_method),
  };
}

export async function fetchContainerStats(
  containerIds: string[],
  signal?: AbortSignal,
): Promise<Record<string, ContainerStatsSummary>> {
  if (!containerIds.length) {
    return {};
  }

  const ids = containerIds.map((item) => item.trim()).filter(Boolean).join(",");
  if (!ids) {
    return {};
  }

  const payload = await requestApi<
    Record<
      string,
      Partial<{
        cpu_percent: unknown;
        memory_percent: unknown;
        memory_used: unknown;
        memory_limit: unknown;
        net_rx: unknown;
        net_tx: unknown;
      }>
    >
  >(`/api/containers/stats?ids=${encodeURIComponent(ids)}`, {
    method: "GET",
    signal,
  });

  return Object.entries(payload).reduce<Record<string, ContainerStatsSummary>>((acc, [id, value]) => {
    acc[id] = {
      cpu_percent: toNullableNumber(value.cpu_percent),
      memory_percent: toNullableNumber(value.memory_percent),
      memory_used: toNullableNumber(value.memory_used),
      memory_limit: toNullableNumber(value.memory_limit),
      net_rx: toNullableNumber(value.net_rx),
      net_tx: toNullableNumber(value.net_tx),
    };
    return acc;
  }, {});
}

const STOPPED_STATUSES = new Set(["stopped", "exited"]);

export function filterContainers(
  containers: ContainerSummary[],
  filter: ContainerFilter,
): ContainerSummary[] {
  if (filter === "all") {
    return containers;
  }
  if (filter === "stopped") {
    // Docker reports stopped containers as "exited"; treat both as stopped to
    // match isActionDisabled and the legacy lifecycle-state handling.
    return containers.filter((container) => STOPPED_STATUSES.has(container.status));
  }
  return containers.filter((container) => container.status === filter);
}

function isValidWebPort(port: number | null | undefined): port is number {
  return typeof port === "number" && Number.isInteger(port) && port > 0 && port <= 65535;
}

export function getContainerWebPort(container: ContainerSummary): number | null {
  if (!container.ports.length) {
    return null;
  }

  const tcpPorts = container.ports.filter((port) => port.protocol !== "udp");
  // Precedence mirrors the legacy page: tcp host port, any host port, tcp
  // container port, any container port. Each candidate must be a valid port
  // (1-65535) so we never produce an http://host:0 (or out-of-range) link.
  const orderedCandidates = [
    tcpPorts.find((port) => isValidWebPort(port.host_port))?.host_port,
    container.ports.find((port) => isValidWebPort(port.host_port))?.host_port,
    tcpPorts.find((port) => isValidWebPort(port.container_port))?.container_port,
    container.ports.find((port) => isValidWebPort(port.container_port))?.container_port,
  ];

  for (const candidate of orderedCandidates) {
    if (isValidWebPort(candidate)) {
      return candidate;
    }
  }
  return null;
}

export function getContainerWebUrl(
  container: ContainerSummary,
  hostname = typeof window === "undefined" ? null : window.location.hostname,
): string | null {
  if (container.web_url) {
    try {
      const explicitUrl = new URL(container.web_url);
      if (
        (explicitUrl.protocol === "http:" || explicitUrl.protocol === "https:") &&
        !explicitUrl.username &&
        !explicitUrl.password
      ) {
        return explicitUrl.href;
      }
    } catch {
      // Invalid metadata is intentionally treated as unavailable.
    }
  }

  const port = getContainerWebPort(container);
  if (!container.web_scheme || !port || !hostname) {
    return null;
  }
  const formattedHostname = hostname.includes(":") && !hostname.startsWith("[")
    ? `[${hostname}]`
    : hostname;
  return `${container.web_scheme}://${formattedHostname}:${port}`;
}
