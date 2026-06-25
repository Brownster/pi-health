import type { ComponentType } from "react";

import { ContainersPage } from "@/pages/containers-page";
import { DashboardHomePage } from "@/pages/dashboard-home";
import { StacksPage } from "@/pages/stacks-page";

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
];

export const navRoutes = appRoutes.filter((route) => route.showInNav);
