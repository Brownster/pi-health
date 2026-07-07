import { useEffect, useMemo, useState } from "react";
import { Eye, Loader2, ShieldAlert, X } from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  type ContainerHealth,
  type ContainerInspect,
  type ContainerSummary,
  fetchContainerHealth,
  fetchContainerInspect,
} from "@/lib/containers";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "Not running";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days ? `${days}d` : "", hours ? `${hours}h` : "", `${minutes}m`]
    .filter(Boolean)
    .join(" ");
}

export function ContainerDetail({
  container,
  onClose,
}: {
  container: ContainerSummary;
  onClose: () => void;
}) {
  const [inspect, setInspect] = useState<ContainerInspect | null>(null);
  const [health, setHealth] = useState<ContainerHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fullEnvironment, setFullEnvironment] = useState<Map<string, string> | null>(null);
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [revealing, setRevealing] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchContainerInspect(container.id, false, controller.signal),
      fetchContainerHealth(container.id, controller.signal),
    ])
      .then(([nextInspect, nextHealth]) => {
        setInspect(nextInspect);
        setHealth(nextHealth);
      })
      .catch((caughtError) => {
        if (!controller.signal.aborted) {
          setError(caughtError instanceof Error ? caughtError.message : "Unable to inspect container");
        }
      });
    return () => controller.abort();
  }, [container.id]);

  const restartPolicy = useMemo(() => {
    const name = inspect?.restart_policy.Name;
    return typeof name === "string" && name ? name : "none";
  }, [inspect]);

  const reveal = async (key: string) => {
    setRevealing(key);
    try {
      let values = fullEnvironment;
      if (!values) {
        const full = await fetchContainerInspect(container.id, true);
        values = new Map(full.environment.map((item) => [item.key, item.value ?? ""]));
        setFullEnvironment(values);
      }
      setRevealed((current) => new Set(current).add(key));
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unable to reveal variable");
    } finally {
      setRevealing(null);
    }
  };

  return (
    <ModalOverlay onClose={onClose}>
      <Card
        aria-labelledby="v2-container-detail-title"
        aria-modal="true"
        className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden"
        id="v2-container-detail"
        role="dialog"
      >
        <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle id="v2-container-detail-title">{container.name}</CardTitle>
              <StatusBadge label={container.status} tone={container.status === "running" ? "success" : "neutral"} />
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{container.id}</p>
          </div>
          <Button aria-label="Close container details" onClick={onClose} variant="outline">
            <X aria-hidden="true" className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-5 overflow-auto p-4 sm:p-5">
          {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
          {!inspect ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Loading details...
            </p>
          ) : (
            <>
              <dl className="grid gap-3 rounded-lg border border-border bg-muted/20 p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
                {[
                  ["Image", inspect.image],
                  ["Stack", inspect.stack ?? "Standalone"],
                  ["Uptime", formatDuration(inspect.uptime_seconds)],
                  ["Restart", restartPolicy],
                  ["Created", inspect.created ?? "Unknown"],
                  ["Started", inspect.started_at ?? "Not running"],
                ].map(([label, value]) => (
                  <div className="min-w-0" key={label}>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
                    <dd className="break-words font-mono text-xs">{value}</dd>
                  </div>
                ))}
              </dl>

              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Healthcheck</h3>
                <div className="rounded-lg border border-border bg-[#080b0f] p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm">
                    <span className={`h-2.5 w-2.5 rounded-full ${health?.status === "healthy" ? "bg-success" : health?.status === "unhealthy" ? "bg-danger" : "bg-muted-foreground"}`} />
                    {health?.status || "none"} · failing streak {health?.failing_streak ?? 0}
                  </div>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-xs text-muted-foreground">{health?.last_output || "No healthcheck output."}</pre>
                </div>
              </section>

              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Mounts</h3>
                <div className="space-y-2">
                  {inspect.mounts.length ? inspect.mounts.map((mount, index) => (
                    <div className="break-all rounded-md border border-border p-2 font-mono text-xs" key={`${mount.destination}-${index}`}>
                      {mount.source || mount.type} → {mount.destination} ({mount.rw ? "rw" : "ro"})
                    </div>
                  )) : <p className="text-sm text-muted-foreground">No mounts.</p>}
                </div>
              </section>

              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Networks</h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {inspect.networks.map((network) => (
                    <div className="rounded-md border border-border p-3 text-xs" key={network.name}>
                      <p className="font-semibold">{network.name}</p>
                      <p className="font-mono text-muted-foreground">{network.ip_address || "No IP"}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="space-y-2">
                <div className="flex items-center gap-2">
                  <ShieldAlert aria-hidden="true" className="h-4 w-4 text-warning" />
                  <h3 className="text-sm font-semibold">Environment keys</h3>
                </div>
                <div className="space-y-2">
                  {inspect.environment.map(({ key }) => (
                    <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3" key={key}>
                      <code className="break-all text-xs">{key}{revealed.has(key) ? `=${fullEnvironment?.get(key) ?? ""}` : ""}</code>
                      {!revealed.has(key) ? (
                        <Button className="gap-1" disabled={revealing === key} onClick={() => void reveal(key)} size="sm" variant="outline">
                          <Eye aria-hidden="true" className="h-3.5 w-3.5" /> Reveal
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </CardContent>
      </Card>
    </ModalOverlay>
  );
}
