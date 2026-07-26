/**
 * Pure readings over container telemetry, kept free of transport imports so the
 * rules stay directly testable.
 */

export interface ContainerMemoryReading {
  status: string;
  memory_used: number | null;
}

/**
 * True when the host cannot account for container memory at all — the kernel was
 * booted without the memory cgroup, so Docker reports nothing rather than zero
 * for every container. One container reporting a real figure disproves it.
 */
export function isMemoryAccountingUnavailable(containers: ContainerMemoryReading[]): boolean {
  const running = containers.filter((container) => container.status === "running");
  return running.length > 0 && running.every((container) => container.memory_used === null);
}
