import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import { fetchAuthSession } from "@/lib/auth";

export type AuthState = "loading" | "authenticated" | "unauthenticated" | "error";

interface AuthContextValue {
  state: AuthState;
  username: string | null;
  error: string | null;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<AuthState>("loading");
  const [username, setUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    setState("loading");
    setError(null);

    try {
      const session = await fetchAuthSession();
      if (!isMountedRef.current) {
        return;
      }

      if (session.authenticated) {
        setState("authenticated");
        setUsername(session.username || "unknown");
        return;
      }

      setState("unauthenticated");
      setUsername(null);
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }

      setState("error");
      setUsername(null);
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Unexpected auth check failure",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthContextValue>(
    () => ({ state, username, error, refresh }),
    [state, username, error, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
