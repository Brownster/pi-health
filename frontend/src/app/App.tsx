import { Navigate, Route, Routes } from "react-router-dom";

import { appRoutes } from "@/app/routes";
import { AuthProvider } from "@/components/auth/auth-provider";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { AppShell } from "@/components/layout/app-shell";
import { ThemeProvider } from "@/components/theme/theme-provider";

export default function App() {
  return (
    <ThemeProvider defaultMode="dark" storageKey="pihealth-v2-theme">
      <AuthProvider>
        <AppShell>
          <Routes>
            {appRoutes.map((route) => {
              const RouteComponent = route.component;
              const element = route.requiresAuth ? (
                <ProtectedRoute>
                  <RouteComponent />
                </ProtectedRoute>
              ) : (
                <RouteComponent />
              );

              return (
                <Route
                  key={route.path}
                  path={route.path}
                  element={element}
                />
              );
            })}
            <Route element={<Navigate replace to="/" />} path="*" />
          </Routes>
        </AppShell>
      </AuthProvider>
    </ThemeProvider>
  );
}
