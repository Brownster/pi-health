import { csrfHeaders, setCsrfToken } from "./api";

export interface AuthSession {
  authenticated: boolean;
  username: string | null;
  csrfToken: string | null;
  role: "admin" | "operator" | "viewer" | null;
  permissions: string[];
}

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthSession> {
  const response = await fetch("/api/auth/check", {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
    signal,
  });

  if (response.status === 401) {
    setCsrfToken(null);
    return {
      authenticated: false,
      username: null,
      csrfToken: null,
      role: null,
      permissions: [],
    };
  }

  if (!response.ok) {
    throw new Error(`Auth check failed with status ${response.status}`);
  }

  const payload = (await response.json()) as {
    authenticated?: boolean;
    username?: string;
    csrf_token?: string;
    role?: "admin" | "operator" | "viewer" | null;
    permissions?: unknown;
  };

  const token = payload.csrf_token ?? null;
  setCsrfToken(token);
  return {
    authenticated: Boolean(payload.authenticated),
    username: payload.username ?? null,
    csrfToken: token,
    role: payload.role ?? null,
    permissions: Array.isArray(payload.permissions)
      ? payload.permissions.filter((permission): permission is string => typeof permission === "string")
      : [],
  };
}

export async function logoutToLogin(): Promise<void> {
  try {
    await fetch("/api/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: await csrfHeaders("POST"),
    });
  } finally {
    window.sessionStorage.removeItem("loggedIn");
    window.sessionStorage.removeItem("username");
    window.location.assign("/login.html");
  }
}
