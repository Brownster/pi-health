export const APP_PATHS = {
  home: "/",
  containers: "/containers",
  stacks: "/stacks",
  apps: "/apps",
  disks: "/disks",
  plugins: "/plugins",
  pools: "/pools",
  mounts: "/mounts",
  shares: "/shares",
  system: "/system",
  network: "/network",
  integrations: "/integrations",
  settings: "/settings",
  extensions: "/settings/extensions",
} as const;

export const APP_ROUTE_PATTERNS = {
  extensionDetails: `${APP_PATHS.extensions}/:extensionId`,
  poolProviderDetails: `${APP_PATHS.pools}/:providerId`,
} as const;

export function extensionDetailsPath(extensionId: string): string {
  return `${APP_PATHS.extensions}/${encodeURIComponent(extensionId)}`;
}

export function poolProviderPath(providerId: string): string {
  return `${APP_PATHS.pools}/${encodeURIComponent(providerId)}`;
}

// CP-019 activates this redirect after Pools and Protection own provider workflows.
export const PLUGINS_ROUTE_COMPATIBILITY = {
  legacyPath: APP_PATHS.plugins,
  redirectTarget: APP_PATHS.extensions,
  redirectEnabled: false,
} as const;
