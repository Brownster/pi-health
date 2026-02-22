import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "system";

interface ThemeProviderProps {
  children: ReactNode;
  defaultMode?: ThemeMode;
  storageKey?: string;
}

interface ThemeProviderState {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

const defaultState: ThemeProviderState = {
  mode: "dark",
  setMode: () => undefined,
};

const ThemeProviderContext = createContext<ThemeProviderState>(defaultState);

const MEDIA_QUERY = "(prefers-color-scheme: dark)";

function resolveSystemMode(): "light" | "dark" {
  if (typeof window === "undefined") {
    return "dark";
  }

  return window.matchMedia(MEDIA_QUERY).matches ? "dark" : "light";
}

function applyThemeClass(mode: ThemeMode): void {
  if (typeof document === "undefined") {
    return;
  }

  const root = document.documentElement;
  const resolvedMode = mode === "system" ? resolveSystemMode() : mode;

  root.classList.remove("light", "dark");
  root.classList.add(resolvedMode);
  root.dataset.theme = mode;
}

export function ThemeProvider({
  children,
  defaultMode = "dark",
  storageKey = "pihealth-v2-theme",
}: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") {
      return defaultMode;
    }

    const storedMode = window.localStorage.getItem(storageKey);
    if (storedMode === "light" || storedMode === "dark" || storedMode === "system") {
      return storedMode;
    }

    return defaultMode;
  });

  useEffect(() => {
    applyThemeClass(mode);

    if (mode !== "system" || typeof window === "undefined") {
      return undefined;
    }

    const media = window.matchMedia(MEDIA_QUERY);
    const onModeChange = () => applyThemeClass("system");

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onModeChange);
      return () => media.removeEventListener("change", onModeChange);
    }

    media.addListener(onModeChange);
    return () => media.removeListener(onModeChange);
  }, [mode]);

  const setMode = useCallback((nextMode: ThemeMode) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(storageKey, nextMode);
    }
    setModeState(nextMode);
  }, [storageKey]);

  const value = useMemo(() => ({ mode, setMode }), [mode, setMode]);

  return (
    <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeProviderContext);
}
