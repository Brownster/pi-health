import { useCallback, useEffect, useRef, useState } from "react";

export type LiveRefreshInterval = 30 | 60;

export interface LiveRefreshPreference {
  enabled: boolean;
  intervalSeconds: LiveRefreshInterval;
}

export const LIVE_REFRESH_STORAGE_KEY = "limeos.liveRefresh.v1";
const LIVE_REFRESH_EVENT = "limeos:live-refresh-change";
export const DEFAULT_LIVE_REFRESH: LiveRefreshPreference = {
  enabled: false,
  intervalSeconds: 30,
};

export function parseLiveRefreshPreference(raw: string | null): LiveRefreshPreference {
  if (!raw) {
    return DEFAULT_LIVE_REFRESH;
  }
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    if (
      typeof value.enabled !== "boolean" ||
      (value.interval_seconds !== 30 && value.interval_seconds !== 60)
    ) {
      return DEFAULT_LIVE_REFRESH;
    }
    return {
      enabled: value.enabled,
      intervalSeconds: value.interval_seconds,
    };
  } catch {
    return DEFAULT_LIVE_REFRESH;
  }
}

function readPreference(): LiveRefreshPreference {
  if (typeof window === "undefined") {
    return DEFAULT_LIVE_REFRESH;
  }
  try {
    return parseLiveRefreshPreference(window.localStorage.getItem(LIVE_REFRESH_STORAGE_KEY));
  } catch {
    return DEFAULT_LIVE_REFRESH;
  }
}

function storePreference(preference: LiveRefreshPreference): void {
  try {
    window.localStorage.setItem(
      LIVE_REFRESH_STORAGE_KEY,
      JSON.stringify({
        enabled: preference.enabled,
        interval_seconds: preference.intervalSeconds,
      }),
    );
  } catch {
    // A blocked localStorage should not prevent manual refresh.
  }
  window.dispatchEvent(new CustomEvent(LIVE_REFRESH_EVENT, { detail: preference }));
}

export function useLiveRefresh(onRefresh: () => void) {
  const [preference, setPreference] = useState<LiveRefreshPreference>(readPreference);
  const refreshRef = useRef(onRefresh);

  useEffect(() => {
    refreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    const syncFromStorage = (event: StorageEvent) => {
      if (event.key === LIVE_REFRESH_STORAGE_KEY) {
        setPreference(parseLiveRefreshPreference(event.newValue));
      }
    };
    const syncFromPage = (event: Event) => {
      const detail = (event as CustomEvent<LiveRefreshPreference>).detail;
      if (detail) {
        setPreference(detail);
      }
    };
    window.addEventListener("storage", syncFromStorage);
    window.addEventListener(LIVE_REFRESH_EVENT, syncFromPage);
    return () => {
      window.removeEventListener("storage", syncFromStorage);
      window.removeEventListener(LIVE_REFRESH_EVENT, syncFromPage);
    };
  }, []);

  useEffect(() => {
    if (!preference.enabled) {
      return;
    }

    let intervalId: number | null = null;
    const stop = () => {
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
    };
    const start = () => {
      stop();
      if (document.visibilityState === "visible") {
        intervalId = window.setInterval(
          () => refreshRef.current(),
          preference.intervalSeconds * 1_000,
        );
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        refreshRef.current();
        start();
      } else {
        stop();
      }
    };

    start();
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [preference.enabled, preference.intervalSeconds]);

  const updatePreference = useCallback((next: LiveRefreshPreference) => {
    setPreference(next);
    storePreference(next);
  }, []);

  const setEnabled = useCallback(
    (enabled: boolean) => updatePreference({ ...preference, enabled }),
    [preference, updatePreference],
  );
  const setIntervalSeconds = useCallback(
    (intervalSeconds: LiveRefreshInterval) =>
      updatePreference({ ...preference, intervalSeconds }),
    [preference, updatePreference],
  );

  return { preference, setEnabled, setIntervalSeconds };
}
