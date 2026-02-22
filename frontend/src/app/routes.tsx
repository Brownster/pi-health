import type { ComponentType } from "react";

import { ContainersPlaceholderPage } from "@/pages/containers-placeholder";
import { DashboardHomePage } from "@/pages/dashboard-home";

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
    component: ContainersPlaceholderPage,
  },
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
