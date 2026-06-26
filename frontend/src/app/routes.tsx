import type { ComponentType } from "react";

import { ContainersPage } from "@/pages/containers-page";
import { DashboardHomePage } from "@/pages/dashboard-home";
import { DisksPage } from "@/pages/disks-page";
import { MountsPage } from "@/pages/mounts-page";
import { SettingsPage } from "@/pages/settings-page";
import { SharesPage } from "@/pages/shares-page";
import { StacksPage } from "@/pages/stacks-page";
import { StoragePage } from "@/pages/storage-page";

export interface AppRoute {
  path: string;
  label: string;
  requiresAuth?: boolean;
  showInNav: boolean;
  component: ComponentType;
}

export const appRoutes: AppRoute[] = [
  {
    path: "/",
    label: "Overview",
    showInNav: true,
    component: DashboardHomePage,
  },
  {
    path: "/containers",
    label: "Containers",
    requiresAuth: true,
    showInNav: true,
    component: ContainersPage,
  },
  {
    path: "/stacks",
    label: "Stacks",
    requiresAuth: true,
    showInNav: true,
    component: StacksPage,
  },
  {
    path: "/disks",
    label: "Disks",
    requiresAuth: true,
    showInNav: true,
    component: DisksPage,
  },
  {
    path: "/plugins",
    label: "Plugins",
    requiresAuth: true,
    showInNav: true,
    component: StoragePage,
  },
  {
    path: "/pools",
    label: "Pools",
    requiresAuth: true,
    showInNav: true,
    component: StoragePage,
  },
  {
    path: "/mounts",
    label: "Mounts",
    requiresAuth: true,
    showInNav: true,
    component: MountsPage,
  },
  {
    path: "/shares",
    label: "Shares",
    requiresAuth: true,
    showInNav: true,
    component: SharesPage,
  },
  {
    path: "/settings",
    label: "Settings",
    requiresAuth: true,
    showInNav: true,
    component: SettingsPage,
  },
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
