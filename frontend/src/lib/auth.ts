export interface AuthSession {
  authenticated: boolean;
  username: string | null;
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
    return {
      authenticated: false,
      username: null,
    };
  }

  if (!response.ok) {
    throw new Error(`Auth check failed with status ${response.status}`);
  }

  const payload = (await response.json()) as {
    authenticated?: boolean;
    username?: string;
  };

  return {
    authenticated: Boolean(payload.authenticated),
    username: payload.username ?? null,
  };
}
