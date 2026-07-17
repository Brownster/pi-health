import type { ComponentType } from "react";

import { CatalogPage } from "@/pages/catalog-page";
import { ContainersPage } from "@/pages/containers-page";
import { DashboardHomePage } from "@/pages/dashboard-home";
import { DisksPage } from "@/pages/disks-page";
import { ExtensionsPage } from "@/pages/extensions-page";
import { MountsPage } from "@/pages/mounts-page";
import { IntegrationsPage } from "@/pages/integrations-page";
import { NetworkPage } from "@/pages/network-page";
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
    path: "/",
    label: "Home",
    navGroup: "Main",
    requiresAuth: true,
    showInNav: true,
    component: DashboardHomePage,
  },
  {
    path: "/containers",
    label: "Containers",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: ContainersPage,
  },
  {
    path: "/stacks",
    label: "Stacks",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: StacksPage,
  },
  {
    path: "/apps",
    label: "App Catalog",
    navGroup: "My Apps",
    requiresAuth: true,
    showInNav: true,
    component: CatalogPage,
  },
  {
    path: "/disks",
    label: "Disks",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: DisksPage,
  },
  {
    path: "/plugins",
    label: "Plugins",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: StoragePage,
  },
  {
    path: "/pools",
    label: "Pools",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: StoragePage,
  },
  {
    path: "/mounts",
    label: "Mounts",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: MountsPage,
  },
  {
    path: "/shares",
    label: "Shares",
    navGroup: "Storage",
    requiresAuth: true,
    showInNav: true,
    component: SharesPage,
  },
  {
    path: "/system",
    label: "System Health",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: SystemPage,
  },
  {
    path: "/network",
    label: "Network",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: NetworkPage,
  },
  {
    path: "/integrations",
    label: "Integrations",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: IntegrationsPage,
  },
  {
    path: "/settings",
    label: "Settings",
    navGroup: "System",
    requiresAuth: true,
    showInNav: true,
    component: SettingsPage,
  },
  {
    path: "/settings/extensions",
    label: "Extensions",
    navGroup: "System",
    requiresAuth: true,
    showInNav: false,
    component: ExtensionsPage,
  },
  {
    path: "/settings/extensions/:extensionId",
    label: "Extension details",
    navGroup: "System",
    requiresAuth: true,
    showInNav: false,
    component: ExtensionsPage,
  },
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
