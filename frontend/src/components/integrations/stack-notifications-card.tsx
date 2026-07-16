import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Film,
  Loader2,
  Plus,
  TriangleAlert,
  X,
} from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  enableStackNotifications,
  getStackNotificationsStatus,
  setStackNotificationsMode,
  type StackNotificationsStatus,
} from "@/lib/integrations";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed";
}

function ingestUrl(token: string): string {
  return `${window.location.origin}/api/integrations/stack-notifications/hook/${token}`;
}

export function StackNotificationsCard({ refreshKey }: { refreshKey?: number }) {
  const [status, setStatus] = useState<StackNotificationsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingMode, setSavingMode] = useState(false);
  const [copied, setCopied] = useState(false);
  const [enableOpen, setEnableOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [enabling, setEnabling] = useState(false);
  const [enableLines, setEnableLines] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      setStatus(await getStackNotificationsStatus());
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function toggleMode() {
    if (!status) return;
    const next = status.mode === "quiet" ? "verbose" : "quiet";
    setSavingMode(true);
    try {
      setStatus(await setStackNotificationsMode(next));
      setNotice(next === "verbose" ? "Verbose: every event is forwarded." : "Quiet: only imports, upgrades, health, and failures.");
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSavingMode(false);
    }
  }

  async function copyUrl() {
    if (!status?.token) return;
    try {
      await navigator.clipboard.writeText(ingestUrl(status.token));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Copy failed — select and copy the URL manually.");
    }
  }

  async function runEnable() {
    setEnabling(true);
    setEnableLines(["Connecting to Mattermost..."]);
    setError(null);
    try {
      await enableStackNotifications(password, (event) => {
        if (event.line) setEnableLines((current) => [...current, event.line as string]);
        if (event.error) setEnableLines((current) => [...current, event.error as string]);
      });
      setPassword("");
      setEnableOpen(false);
      setNotice("Stack notifications channel is ready.");
      await load();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setEnabling(false);
    }
  }

  const configured = Boolean(status?.configured);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border/70 bg-muted/20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary">
              <Film className="h-5 w-5" />
            </span>
            <div>
              <CardTitle>Stack notifications</CardTitle>
              <CardDescription>Radarr / Sonarr / *arr events in a dedicated Mattermost channel</CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge
              label={configured ? (status?.enabled ? "connected" : "disabled") : "not set up"}
              tone={configured && status?.enabled ? "success" : "neutral"}
            />
            {!configured ? (
              <Button className="gap-2" data-stack-notifications-enable onClick={() => setEnableOpen(true)}>
                <Plus className="h-4 w-4" />Set up
              </Button>
            ) : null}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 p-4 sm:p-6">
        {notice ? (
          <div className="flex items-center justify-between gap-3 border-l-2 border-success bg-success/5 px-3 py-2 text-sm text-success" role="status">
            <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4" />{notice}</span>
            <Button aria-label="Dismiss" className="h-8 min-h-8 w-8 px-0" onClick={() => setNotice(null)} variant="ghost"><X className="h-4 w-4" /></Button>
          </div>
        ) : null}
        {error ? (
          <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-sm text-danger" role="alert">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}
          </div>
        ) : null}

        {configured ? (
          <div className="space-y-4">
            <div>
              <p className="font-mono text-[10px] uppercase text-dim">Webhook URL for your *arr apps</p>
              <div className="mt-1 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-black/30 px-3 py-2 font-mono text-xs" data-stack-notifications-url title={status?.token ? ingestUrl(status.token) : ""}>
                  {status?.token ? ingestUrl(status.token) : "—"}
                </code>
                <Button aria-label="Copy webhook URL" className="h-9 min-h-9 gap-1 px-2" onClick={() => void copyUrl()} variant="outline">
                  {copied ? <CheckCircle2 className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                In each app add a <strong>Webhook</strong> connection (Settings → Connect), method POST, to this URL. Delivers to
                {" "}~{status?.channel_name ?? "stack-notifications"}.
              </p>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-md border border-border p-3">
              <div>
                <p className="text-sm font-medium">Forwarding</p>
                <p className="text-xs text-muted-foreground">
                  {status?.mode === "verbose"
                    ? "Verbose — every event including grabs and renames."
                    : "Quiet — imports, upgrades, health, and failures only."}
                </p>
              </div>
              <label className="inline-flex min-h-11 cursor-pointer items-center gap-2">
                <span className="text-xs text-muted-foreground">{status?.mode === "verbose" ? "Verbose" : "Quiet"}</span>
                <input checked={status?.mode === "verbose"} className="h-5 w-5 accent-primary" disabled={savingMode} onChange={() => void toggleMode()} type="checkbox" />
              </label>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Create a dedicated <span className="font-mono">~stack-notifications</span> channel and a webhook your *arr apps post to.
            New Mattermost installs get this automatically; use <strong>Set up</strong> to add it to an existing install.
          </p>
        )}
      </CardContent>

      {enableOpen ? (
        <ModalOverlay onClose={enabling ? () => undefined : () => setEnableOpen(false)}>
          <Card aria-labelledby="stack-notifications-enable-title" aria-modal="true" className="w-full max-w-md" role="dialog">
            <CardHeader className="flex flex-row items-start justify-between border-b border-border">
              <div>
                <CardTitle id="stack-notifications-enable-title">Set up stack notifications</CardTitle>
                <CardDescription>Confirm your Mattermost admin password to create the channel and webhook.</CardDescription>
              </div>
              <Button aria-label="Close" className="w-11 px-0" disabled={enabling} onClick={() => setEnableOpen(false)} variant="ghost"><X className="h-4 w-4" /></Button>
            </CardHeader>
            <CardContent className="space-y-4 p-4 sm:p-6">
              {enabling || enableLines.length ? (
                <div className="space-y-3">
                  <div className={cn("flex items-center gap-2 text-sm", error ? "text-danger" : "text-info")}>
                    {enabling ? <Loader2 className="h-4 w-4 animate-spin" /> : error ? <TriangleAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                    {enabling ? "Creating channel" : error ? "Setup failed" : "Done"}
                  </div>
                  <pre className="max-h-56 overflow-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground">{enableLines.join("\n")}</pre>
                  {!enabling ? <Button onClick={() => setEnableOpen(false)}>Close</Button> : null}
                </div>
              ) : (
                <>
                  <label className="space-y-1">
                    <span className="text-xs text-muted-foreground">Mattermost admin password</span>
                    <input autoComplete="current-password" className={FIELD_CLASS} onChange={(event) => setPassword(event.target.value)} type="password" value={password} />
                  </label>
                  <Button className="w-full gap-2" data-stack-notifications-confirm disabled={password.length < 1} onClick={() => void runEnable()}>
                    <Film className="h-4 w-4" />Create channel
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </Card>
  );
}
