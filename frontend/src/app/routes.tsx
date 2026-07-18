import type { ComponentType } from "react";

import {
  APP_PATHS,
  APP_ROUTE_PATTERNS,
  PLUGINS_ROUTE_COMPATIBILITY,
} from "@/app/route-contract";
import { CatalogPage } from "@/pages/catalog-page";
import { ContainersPage } from "@/pages/containers-page";
import { DashboardHomePage } from "@/pages/dashboard-home";
import { DisksPage } from "@/pages/disks-page";
import { ExtensionsPage } from "@/pages/extensions-page";
import { MountsPage } from "@/pages/mounts-page";
import { IntegrationsPage } from "@/pages/integrations-page";
import { NetworkPage } from "@/pages/network-page";
import { PoolsPage } from "@/pages/pools-page";
import { SettingsPage } from "@/pages/settings-page";
import { SharesPage } from "@/pages/shares-page";
import { StacksPage } from "@/pages/stacks-page";
import { StoragePage } from "@/pages/storage-page";
import { SystemPage } from "@/pages/system-page";

export interface AppRoute {
  path: string;
  label: string;
  navGroup: "Main" | "My Apps" | "Storage" | "System";
  requiresAuth?: boolean;
  showInNav: boolean;
  component: ComponentType;
}

export const appRoutes: AppRoute[] = [
  {
    path: APP_PATHS.home,
    label: "Home",
    navGroup: "Main",
    requiresAuth: true,
    showInNav: true,
    component: DashboardHomePage,
  },
  {
    path: APP_PATHS.containers,
    label: "Containers",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: ContainersPage,
  },
  {
    path: APP_PATHS.stacks,
    label: "Stacks",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: StacksPage,
  },
  {
    path: APP_PATHS.apps,
    label: "App Catalog",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: CatalogPage,
  },
  {
    path: APP_PATHS.disks,
    label: "Disks",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: DisksPage,
  },
  {
    path: PLUGINS_ROUTE_COMPATIBILITY.legacyPath,
    label: "Plugins",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: StoragePage,
  },
  {
    path: APP_PATHS.pools,
    label: "Pools",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: PoolsPage,
  },
  {
    path: APP_ROUTE_PATTERNS.poolProviderDetails,
    label: "Pool provider",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: false,
    component: PoolsPage,
  },
  {
    path: APP_PATHS.mounts,
    label: "Mounts",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: MountsPage,
  },
  {
    path: APP_PATHS.shares,
    label: "Shares",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: SharesPage,
  },
  {
    path: APP_PATHS.system,
    label: "System Health",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: SystemPage,
  },
  {
    path: APP_PATHS.network,
    label: "Network",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: NetworkPage,
  },
  {
    path: APP_PATHS.integrations,
    label: "Integrations",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: IntegrationsPage,
  },
  {
    path: APP_PATHS.settings,
    label: "Settings",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: SettingsPage,
  },
  {
    path: APP_PATHS.extensions,
    label: "Extensions",
    navGroup: "System",
    requiresAuth: true,
    showInNav: false,
    component: ExtensionsPage,
  },
  {
    path: APP_ROUTE_PATTERNS.extensionDetails,
    label: "Extension details",
    navGroup: "System",
    requiresAuth: true,
    showInNav: false,
    component: ExtensionsPage,
  },
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
