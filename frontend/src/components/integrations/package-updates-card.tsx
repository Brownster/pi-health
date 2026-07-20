import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, PackageCheck, ShieldAlert, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  approvePackageUpdate,
  getPendingPackageUpdates,
  type PendingPackageUpdate,
} from "@/lib/integrations";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed";
}

/**
 * Held/critical package updates the nightly job won't auto-apply. Approving one records an
 * authenticated, payload-bound override; the next nightly reconcile applies and holds it.
 */
export function PackageUpdatesCard({ refreshKey }: { refreshKey?: number }) {
  const [pending, setPending] = useState<PendingPackageUpdate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await getPendingPackageUpdates(signal);
      setPending(result.pending ?? []);
      setError(null);
    } catch (caught) {
      if (!signal?.aborted) setError(errorMessage(caught));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshKey]);

  async function approve(update: PendingPackageUpdate) {
    setApproving(update.name);
    try {
      await approvePackageUpdate(update.name, update.candidate);
      await load();
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setApproving(null);
    }
  }

  // Nothing to review and nothing errored: keep the page quiet.
  if (pending !== null && pending.length === 0 && !error) {
    return null;
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border/70 bg-muted/20">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-md border border-warning/30 bg-warning/10 text-warning">
            <PackageCheck className="h-5 w-5" />
          </span>
          <div>
            <CardTitle>Package updates</CardTitle>
            <CardDescription>Held updates awaiting approval — applied on the next nightly run</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4 sm:p-6">
        {error ? (
          <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-sm text-danger" role="alert">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}
          </div>
        ) : null}
        <ul className="divide-y divide-border rounded-md border border-border">
          {(pending ?? []).map((update) => (
            <li className="flex flex-wrap items-center justify-between gap-3 p-3" key={update.name} data-package-update={update.name}>
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {update.name}
                  {update.critical ? (
                    <Badge tone="danger" className="gap-1"><ShieldAlert className="h-3 w-3" />critical</Badge>
                  ) : null}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {update.installed ?? "—"} → {update.candidate}
                </p>
              </div>
              {update.approved ? (
                <span className="flex items-center gap-1.5 text-sm text-success">
                  <CheckCircle2 className="h-4 w-4" />Approved — applies next run
                </span>
              ) : (
                <Button
                  data-approve={update.name}
                  disabled={approving === update.name}
                  onClick={() => void approve(update)}
                  size="sm"
                >
                  {approving === update.name ? "Approving…" : `Approve ${update.candidate}`}
                </Button>
              )}
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          Approving records who approved what; the nightly reconcile then installs and holds the approved
          version. A newer release from the fleet manifest always takes precedence.
        </p>
      </CardContent>
    </Card>
  );
}
