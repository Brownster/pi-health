import type { ComponentType } from "react";

import { createComingSoonPage } from "@/pages/coming-soon-page";
import { ContainersPage } from "@/pages/containers-page";
import { DashboardHomePage } from "@/pages/dashboard-home";
import { StacksPage } from "@/pages/stacks-page";

// Phase 3 (PH3-001) placeholder routes: reachable v2 shell routes behind the auth
// guard, each replaced by a real page as its ticket lands. Kept out of the nav
// (showInNav: false) until implemented so the shell nav stays uncluttered.
const PHASE3_PLACEHOLDERS: Array<{ path: string; label: string; legacyHref: string }> = [
  { path: "/disks", label: "Disks", legacyHref: "/disks.html" },
  { path: "/pools", label: "Pools", legacyHref: "/pools.html" },
  { path: "/mounts", label: "Mounts", legacyHref: "/mounts.html" },
  { path: "/shares", label: "Shares", legacyHref: "/shares.html" },
  { path: "/plugins", label: "Plugins", legacyHref: "/plugins.html" },
  { path: "/settings", label: "Settings", legacyHref: "/settings.html" },
];

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
  ...PHASE3_PLACEHOLDERS.map<AppRoute>(({ path, label, legacyHref }) => ({
    path,
    label,
    requiresAuth: true,
    showInNav: false,
    component: createComingSoonPage({ title: label, legacyHref }),
  })),
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
