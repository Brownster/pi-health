import { csrfHeaders, setCsrfToken } from "./api";

export interface AuthSession {
  authenticated: boolean;
  username: string | null;
  csrfToken: string | null;
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
    };
  }

  if (!response.ok) {
    throw new Error(`Auth check failed with status ${response.status}`);
  }

  const payload = (await response.json()) as {
    authenticated?: boolean;
    username?: string;
    csrf_token?: string;
  };

  const token = payload.csrf_token ?? null;
  setCsrfToken(token);
  return {
    authenticated: Boolean(payload.authenticated),
    username: payload.username ?? null,
    csrfToken: token,
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
