import type {
  CapabilityHealthState,
  CapabilityTone,
  ExtensionDescriptor,
} from "./capabilities";

export interface ExtensionGroup {
  id: string;
  label: string;
  extensions: ExtensionDescriptor[];
}

const SURFACE_LINKS: Record<string, string> = {
  integrations: "/integrations",
  mounts: "/mounts",
  pools: "/pools",
  shares: "/shares",
};

export function humanizeCapabilityId(value: string): string {
  const label = value.replace(/[._-]+/g, " ").trim();
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : "Other capabilities";
}

export function capabilitySurfaceLink(surface: string): string | null {
  return SURFACE_LINKS[surface] ?? null;
}

export function groupExtensions(extensions: ExtensionDescriptor[]): ExtensionGroup[] {
  const groups = new Map<string, ExtensionDescriptor[]>();
  for (const extension of extensions) {
    const primaryCapability = extension.capabilities[0]?.id ?? "other";
    const group = groups.get(primaryCapability) ?? [];
    group.push(extension);
    groups.set(primaryCapability, group);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => {
      if (left === "other") return 1;
      if (right === "other") return -1;
      return left.localeCompare(right);
    })
    .map(([id, items]) => ({
      id,
      label: id === "other" ? "Other capabilities" : humanizeCapabilityId(id),
      extensions: [...items].sort((left, right) => left.name.localeCompare(right.name)),
    }));
}

export function healthTone(
  health: CapabilityHealthState,
): CapabilityTone {
  if (health === "healthy") return "success";
  if (health === "warning" || health === "unconfigured") return "warning";
  if (health === "error" || health === "incompatible" || health === "unavailable") {
    return "danger";
  }
  return "neutral";
}

export function extensionUpdateLabel(extension: ExtensionDescriptor): string {
  if (extension.update_state === "available") return "update available";
  if (extension.update_state === "current") return "current";
  return "not reported";
}
