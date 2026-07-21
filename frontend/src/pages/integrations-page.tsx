import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Ban,
  BellRing,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  ExternalLink,
  Loader2,
  MessageSquare,
  Plus,
  Power,
  RefreshCw,
  Send,
  ServerCog,
  ShieldAlert,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { AgentsIntegrationCard } from "@/components/integrations/agents-integration-card";
import { IntegrationLifecycleDialog } from "@/components/integrations/integration-lifecycle-dialog";
import { PackageUpdatesCard } from "@/components/integrations/package-updates-card";
import { StackNotificationsCard } from "@/components/integrations/stack-notifications-card";
import { useIntegrationLifecycle } from "@/components/integrations/use-integration-lifecycle";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  disableMattermost,
  enableMattermost,
  getMattermostStatus,
  installMattermost,
  purgeMattermost,
  retryMattermostCleanup,
  sendMattermostTest,
  uninstallMattermost,
  updateMattermostPolicy,
  type AlertKind,
  type AlertPolicy,
  type AlertResource,
  type MattermostSetup,
  type MattermostStatus,
} from "@/lib/integrations";
import {
  lifecycleNavigationTarget,
  type IntegrationBlockedAction,
} from "@/lib/integration-lifecycle-contract";
import { handleTabKeyDown } from "@/lib/tab-keyboard";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const EMPTY_SETUP: MattermostSetup = {
  site_url: `${window.location.protocol}//${window.location.hostname}:8065`,
  admin_username: "limeadmin",
  admin_email: "",
  admin_password: "",
  stack_name: "mattermost",
  team_name: "limeos",
  channel_name: "limeos-alerts",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/London",
  poll_seconds: 60,
  fail_threshold: 2,
};
const KIND_LABELS: Record<AlertKind, { label: string; description: string }> = {
  container: { label: "Containers", description: "Long-running containers that stop or become unhealthy" },
  smart: { label: "SMART", description: "Disk health assessments that report a failure" },
  mount: { label: "Mounts", description: "Required mountpoints that disappear" },
  snapraid: { label: "SnapRAID", description: "Parity errors, degradation, or a required sync" },
};

type Tab = "overview" | "policy";
type SilenceDraft = { resource: AlertResource; duration: "1h" | "24h" | "permanent"; reason: string };
type MattermostLifecycleMode =
  | "disable"
  | "enable"
  | "uninstall"
  | "purge"
  | "retry_disable"
  | "retry_enable"
  | "retry_uninstall"
  | "retry_purge";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed";
}

function formatTime(value?: string | number | null): string {
  if (!value) return "Never";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function statusTone(state: MattermostStatus["state"]): "success" | "warning" | "danger" | "neutral" {
  if (state === "connected") return "success";
  if (state === "degraded" || state === "retained_data") return "warning";
  if (state === "disconnected" || state === "cleanup_required") return "danger";
  return "neutral";
}

function displayState(value: string): string {
  return value.replace(/_/g, " ");
}

export function IntegrationsPage() {
  const { permissions: sessionPermissions } = useAuth();
  const [status, setStatus] = useState<MattermostStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [setupOpen, setSetupOpen] = useState(false);
  const [setup, setSetup] = useState<MattermostSetup>(EMPTY_SETUP);
  const [installing, setInstalling] = useState(false);
  const [installLines, setInstallLines] = useState<string[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [mountDraft, setMountDraft] = useState("");
  const [silenceDraft, setSilenceDraft] = useState<SilenceDraft | null>(null);
  const [testing, setTesting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [integrationRefreshKey, setIntegrationRefreshKey] = useState(0);
  const [lifecycleMode, setLifecycleMode] = useState<MattermostLifecycleMode | null>(null);
  const [blockedAction, setBlockedAction] = useState<IntegrationBlockedAction | null>(null);

  const invalidateIntegrations = useCallback(() => {
    setIntegrationRefreshKey((current) => current + 1);
  }, []);
  const lifecycle = useIntegrationLifecycle(invalidateIntegrations);

  const load = useCallback(async () => {
    try {
      const next = await getMattermostStatus();
      setStatus(next);
      setMountDraft(next.policy.required_mounts.join(", "));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [integrationRefreshKey, load]);

  const resourcesByKind = useMemo(() => {
    const grouped: Record<AlertKind, AlertResource[]> = {
      container: [],
      smart: [],
      mount: [],
      snapraid: [],
    };
    status?.resources.forEach((resource) => grouped[resource.kind]?.push(resource));
    return grouped;
  }, [status]);

  async function runInstall() {
    setInstalling(true);
    setInstallLines(["Starting Mattermost setup..."]);
    setError(null);
    try {
      await installMattermost(setup, (event) => {
        if (event.line) setInstallLines((current) => [...current, event.line as string]);
        if (event.error) {
          setError(event.error);
          setInstallLines((current) => [...current, event.error as string]);
        }
      });
      invalidateIntegrations();
      setNotice("Mattermost and LimeOS alerts are connected.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setInstalling(false);
    }
  }

  async function savePolicy(next: AlertPolicy, successMessage?: string) {
    if (!status) return;
    const previous = status.policy;
    setStatus({ ...status, policy: next });
    setSavingPolicy(true);
    try {
      const saved = await updateMattermostPolicy(next);
      setStatus((current) => (current ? { ...current, policy: saved } : current));
      setNotice(successMessage ?? "Alert policy saved.");
      setError(null);
    } catch (caught) {
      setStatus((current) => (current ? { ...current, policy: previous } : current));
      setError(errorMessage(caught));
    } finally {
      setSavingPolicy(false);
    }
  }

  function toggleCategory(kind: AlertKind) {
    if (!status) return;
    void savePolicy({
      ...status.policy,
      categories: {
        ...status.policy.categories,
        [kind]: { enabled: !status.policy.categories[kind].enabled },
      },
    });
  }

  function activeSilence(resource: AlertResource) {
    return status?.policy.silences.find((item) => item.kind === resource.kind && item.key === resource.key);
  }

  function confirmSilence() {
    if (!status || !silenceDraft) return;
    const now = new Date();
    const expires = new Date(now);
    if (silenceDraft.duration === "1h") expires.setHours(expires.getHours() + 1);
    if (silenceDraft.duration === "24h") expires.setHours(expires.getHours() + 24);
    const next: AlertPolicy = {
      ...status.policy,
      silences: [
        ...status.policy.silences.filter((item) => item.key !== silenceDraft.resource.key),
        {
          kind: silenceDraft.resource.kind,
          key: silenceDraft.resource.key,
          created_at: now.toISOString(),
          expires_at: silenceDraft.duration === "permanent" ? null : expires.toISOString(),
          reason: silenceDraft.reason.trim(),
        },
      ],
    };
    setSilenceDraft(null);
    void savePolicy(next, `${silenceDraft.resource.key} silenced.`);
  }

  async function sendTest() {
    setTesting(true);
    try {
      await sendMattermostTest();
      setNotice("Test alert sent to Mattermost.");
      setError(null);
      await load();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setTesting(false);
    }
  }

  function openLifecycle(mode: MattermostLifecycleMode) {
    setLifecycleMode(mode);
    lifecycle.open();
  }

  function closeLifecycle() {
    if (lifecycle.state.phase === "running") return;
    lifecycle.close();
    setLifecycleMode(null);
  }

  async function runLifecycle(confirmation?: string, acknowledged = false) {
    const mode = lifecycleMode;
    if (!mode) return;
    const action = mode.replace("retry_", "") as "disable" | "enable" | "uninstall" | "purge";
    const retrying = mode.startsWith("retry_");
    if ((action === "uninstall" || action === "purge") && confirmation !== "Mattermost") return;
    if (action === "purge" && !acknowledged) return;

    const values = action === "uninstall"
      ? { confirmation: "Mattermost" }
      : action === "purge"
        ? { confirmation: "Mattermost", acknowledge_data_loss: true }
        : {};
    const completed = await lifecycle.run((onEvent) => {
      if (retrying) return retryMattermostCleanup(action, values, onEvent);
      if (action === "disable") return disableMattermost(onEvent);
      if (action === "enable") return enableMattermost(onEvent);
      if (action === "uninstall") return uninstallMattermost("Mattermost", onEvent);
      return purgeMattermost("Mattermost", onEvent);
    });
    if (!completed) return;
    setNotice(
      action === "disable"
        ? "Mattermost and alert delivery are disabled. Configuration and chat data are preserved."
        : action === "enable"
          ? "Mattermost and alert delivery are enabled."
          : action === "uninstall"
            ? "Mattermost was uninstalled. Chat data is retained for reinstall or deletion."
            : "Mattermost and all retained chat data were deleted.",
    );
  }

  function retryLifecycle() {
    if (lifecycleMode === "uninstall" || lifecycleMode === "retry_uninstall") {
      setLifecycleMode("retry_uninstall");
      lifecycle.reconfirm();
      return;
    }
    if (lifecycleMode === "purge" || lifecycleMode === "retry_purge") {
      setLifecycleMode("retry_purge");
      lifecycle.reconfirm();
      return;
    }
    void lifecycle.retry();
  }

  function focusBlockedDependency(blocker: IntegrationBlockedAction) {
    const target = lifecycleNavigationTarget(blocker);
    if (!target) return;
    setBlockedAction(null);
    window.requestAnimationFrame(() => {
      const card = document.getElementById(target.anchor);
      card?.scrollIntoView({ behavior: "smooth", block: "center" });
      card?.focus();
    });
  }

  const canAdmin = sessionPermissions.includes("extensions.admin");
  const allowedActions = new Set(status?.allowed_actions ?? []);
  const cleanupAction = status?.cleanup_operation?.action;
  const cleanupMode = status?.cleanup_operation?.retryable
    ? cleanupAction === "disable"
      ? "retry_disable"
      : cleanupAction === "enable"
        ? "retry_enable"
        : cleanupAction === "uninstall"
          ? "retry_uninstall"
          : cleanupAction === "purge"
            ? "retry_purge"
            : null
    : null;
  const managementItems: ActionMenuItem[] = [];
  if (allowedActions.has("enable")) {
    managementItems.push({ id: "enable", label: "Enable", Icon: Power, onSelect: () => openLifecycle("enable"), tone: "info", data: { "data-mattermost-lifecycle-action": "enable" } });
  }
  if (allowedActions.has("disable")) {
    managementItems.push({ id: "disable", label: "Disable", Icon: Ban, onSelect: () => openLifecycle("disable"), tone: "danger", data: { "data-mattermost-lifecycle-action": "disable" } });
  }
  status?.blocked_actions.forEach((blocker) => {
    managementItems.push({
      id: `blocked-${blocker.action}`,
      label: `${blocker.action === "disable" ? "Disable" : "Uninstall"} (AI Agents first)`,
      Icon: blocker.action === "disable" ? Ban : Trash2,
      onSelect: () => setBlockedAction(blocker),
      separatorBefore: managementItems.length > 0 && blocker.action === "uninstall",
      tone: "danger",
      data: { "data-mattermost-blocked-action": blocker.action },
    });
  });
  if (allowedActions.has("uninstall")) {
    managementItems.push({ id: "uninstall", label: "Uninstall", Icon: Trash2, onSelect: () => openLifecycle("uninstall"), separatorBefore: managementItems.length > 0, tone: "danger", data: { "data-mattermost-lifecycle-action": "uninstall" } });
  }
  if (allowedActions.has("purge")) {
    managementItems.push({ id: "purge", label: "Delete retained data", Icon: Database, onSelect: () => openLifecycle("purge"), separatorBefore: managementItems.length > 0, tone: "danger", data: { "data-mattermost-lifecycle-action": "purge" } });
  }
  if (allowedActions.has("retry_cleanup") && cleanupMode) {
    managementItems.push({ id: "retry_cleanup", label: "Retry cleanup", Icon: RefreshCw, onSelect: () => openLifecycle(cleanupMode), tone: "info", data: { "data-mattermost-lifecycle-action": "retry_cleanup" } });
  }
  const destructiveMode = lifecycleMode === "uninstall"
    || lifecycleMode === "retry_uninstall"
    || lifecycleMode === "purge"
    || lifecycleMode === "retry_purge";
  const purgeMode = lifecycleMode === "purge" || lifecycleMode === "retry_purge";

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <Button className="gap-2" disabled={loading} onClick={() => { setLoading(true); invalidateIntegrations(); }} variant="secondary">
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </Button>
        }
        description="Chat delivery, alert policy, and automation connections"
        title="integrations"
      />

      {notice ? (
        <div className="flex items-center justify-between gap-3 border-l-2 border-success bg-success/5 px-4 py-3 text-sm text-success" role="status">
          <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4" />{notice}</span>
          <Button aria-label="Dismiss notice" className="h-9 min-h-9 w-9 px-0" onClick={() => setNotice(null)} variant="ghost"><X className="h-4 w-4" /></Button>
        </div>
      ) : null}
      {error ? (
        <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-4 py-3 text-sm text-danger" role="alert">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}
        </div>
      ) : null}

      <Card className="overflow-hidden" data-mattermost-integration id="mattermost-integration" tabIndex={-1}>
        <CardHeader className="border-b border-border/70 bg-muted/20">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-md border border-info/30 bg-info/10 text-info">
                <MessageSquare className="h-5 w-5" />
              </span>
              <div>
                <CardTitle>Mattermost</CardTitle>
                <CardDescription>Private chat for LimeOS incidents and agent investigations</CardDescription>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge label={displayState(status?.state ?? "loading")} tone={status ? statusTone(status.state) : "neutral"} />
              {canAdmin && allowedActions.has("setup") && !status?.retained_data ? <Button className="gap-2" data-mattermost-setup onClick={() => setSetupOpen(true)}><Plus className="h-4 w-4" />Set up</Button> : null}
              {canAdmin && managementItems.length ? (
                <ActionMenu
                  items={managementItems}
                  label="Manage Mattermost"
                  menuData={{ "data-mattermost-lifecycle-menu": "mattermost" }}
                  triggerData={{ "data-mattermost-lifecycle-menu-trigger": "mattermost" }}
                />
              ) : null}
            </div>
          </div>
        </CardHeader>

        {status?.cleanup_required ? (
          <CardContent className="space-y-4 p-4 sm:p-6">
            <div className="flex items-start gap-3 border-l-2 border-danger bg-danger/5 px-4 py-3">
              <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div>
                <p className="text-sm font-medium text-danger">Cleanup needs attention</p>
                <p className="mt-1 text-xs text-muted-foreground">Mattermost remains unavailable until LimeOS finishes the interrupted {cleanupAction ? displayState(cleanupAction) : "cleanup"} operation.</p>
              </div>
            </div>
            <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-3">
              <div className="bg-card p-3"><p className="font-mono text-[10px] uppercase text-dim">Operation</p><p className="mt-1 text-sm">{cleanupAction ? displayState(cleanupAction) : "unknown"}</p></div>
              <div className="bg-card p-3"><p className="font-mono text-[10px] uppercase text-dim">Recovery</p><p className="mt-1 text-sm">{status.cleanup_operation?.state ?? "unavailable"}</p></div>
              <div className="bg-card p-3"><p className="font-mono text-[10px] uppercase text-dim">Updated</p><p className="mt-1 text-sm">{formatTime(status.cleanup_operation?.updated_at)}</p></div>
            </div>
            {canAdmin && allowedActions.has("retry_cleanup") && cleanupMode ? (
              <Button className="gap-2" data-mattermost-retry-cleanup onClick={() => openLifecycle(cleanupMode)} variant="warning"><RefreshCw className="h-4 w-4" />Retry cleanup</Button>
            ) : <p className="text-sm text-muted-foreground">{canAdmin ? "Recovery details are unavailable. Refresh the page before retrying." : "An administrator must finish the cleanup."}</p>}
          </CardContent>
        ) : status?.retained_data ? (
          <CardContent className="space-y-5 p-4 sm:p-6">
            <div className="flex items-start gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3">
              <Database aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div>
                <p className="text-sm font-medium">Mattermost data is retained</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">The services and alert delivery are removed. Database records, messages, uploads, plugins, and retained logs remain available for a reinstall.</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {canAdmin && allowedActions.has("setup") ? <Button className="gap-2" data-mattermost-retained-setup onClick={() => setSetupOpen(true)}><Plus className="h-4 w-4" />Set up again</Button> : null}
              {canAdmin && allowedActions.has("purge") ? <Button className="gap-2" data-mattermost-purge onClick={() => openLifecycle("purge")} variant="danger"><Trash2 className="h-4 w-4" />Delete data</Button> : null}
            </div>
            {!allowedActions.has("purge") ? <p className="text-xs text-muted-foreground">Permanent data deletion is not available in this release.</p> : null}
          </CardContent>
        ) : status?.installed ? (
          <>
            <div aria-label="Mattermost views" className="flex overflow-x-auto border-b border-border px-4" role="tablist">
              {(["overview", "policy"] as Tab[]).map((item) => (
                <button
                  aria-controls={`mattermost-panel-${item}`}
                  aria-selected={tab === item}
                  className={cn("min-h-11 border-b-2 px-4 font-mono text-xs capitalize", tab === item ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
                  id={`mattermost-tab-${item}`}
                  key={item}
                  onClick={() => setTab(item)}
                  onKeyDown={handleTabKeyDown}
                  role="tab"
                  tabIndex={tab === item ? 0 : -1}
                  type="button"
                >{item === "policy" ? "Alert policy" : item}</button>
              ))}
            </div>
            <CardContent aria-labelledby={`mattermost-tab-${tab}`} className="p-4 sm:p-6" id={`mattermost-panel-${tab}`} role="tabpanel">
              {tab === "overview" ? (
                <div className="space-y-5">
                  {status.state === "disabled" ? (
                    <div className="flex items-start gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3">
                      <Ban className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                      <div><p className="text-sm font-medium">Mattermost is disabled</p><p className="mt-1 text-xs text-muted-foreground">Chat, alert delivery, and the full managed stack are stopped. Configuration and chat data are preserved.</p></div>
                    </div>
                  ) : null}
                  <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 xl:grid-cols-5">
                    {[
                      ["Site", status.site_url ?? "Unknown"],
                      ["Channel", `~${status.channel}`],
                      ["Webhook", status.webhook_configured ? "Configured" : "Missing"],
                      ["Services", `${Object.values(status.services ?? {}).filter((item) => item.state === "running").length || 3}/3 running`],
                      ["Last delivery", formatTime(status.delivery.at)],
                    ].map(([label, value]) => (
                      <div className="min-w-0 bg-card p-3" key={label}>
                        <p className="font-mono text-[10px] uppercase text-dim">{label}</p>
                        <p className="mt-1 truncate text-sm" title={value}>{value}</p>
                      </div>
                    ))}
                  </div>
                  {status.state !== "disabled" ? <div className="flex flex-wrap gap-2">
                    <Button className="gap-2" disabled={testing} onClick={() => void sendTest()} variant="info">
                      {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                      {testing ? "Sending" : "Send test alert"}
                    </Button>
                    {status.site_url ? <a className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border px-4 font-mono text-sm hover:bg-muted" href={status.site_url} rel="noreferrer" target="_blank">Open Mattermost<ExternalLink className="h-4 w-4" /></a> : null}
                  </div> : null}
                  {status.incidents.length ? (
                    <div>
                      <h3 className="mb-2 font-mono text-sm font-semibold">Active incidents</h3>
                      <div className="divide-y divide-border rounded-md border border-border">
                        {status.incidents.map((incident) => <div className="flex items-start justify-between gap-3 p-3" key={incident.key}><div><p className="text-sm font-medium">{incident.key}</p><p className="text-xs text-muted-foreground">{incident.summary}</p></div><Badge tone={incident.severity === "critical" ? "danger" : "warning"}>{incident.severity}</Badge></div>)}
                      </div>
                    </div>
                  ) : <p className="text-sm text-muted-foreground">No active incidents.</p>}
                </div>
              ) : null}

              {tab === "policy" ? (
                <div className="space-y-5">
                  <div className="flex items-center justify-between"><div><h3 className="font-mono text-sm font-semibold">Alert categories</h3><p className="text-xs text-muted-foreground">Choose which checks can notify Mattermost.</p></div>{savingPolicy ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : null}</div>
                  <div className="divide-y divide-border rounded-md border border-border">
                    {(Object.keys(KIND_LABELS) as AlertKind[]).map((kind) => {
                      const category = KIND_LABELS[kind];
                      const enabled = status.policy.categories[kind].enabled;
                      return <div className="p-3 sm:p-4" key={kind}>
                        <div className="flex items-start justify-between gap-4">
                          <div><p className="text-sm font-medium">{category.label}</p><p className="text-xs text-muted-foreground">{category.description}</p></div>
                          <label className="inline-flex min-h-11 cursor-pointer items-center gap-2"><span className="text-xs text-muted-foreground">{enabled ? "On" : "Off"}</span><input checked={enabled} className="h-5 w-5 accent-primary" disabled={savingPolicy} onChange={() => toggleCategory(kind)} type="checkbox" /></label>
                        </div>
                        {resourcesByKind[kind].length ? <div className="mt-3 grid gap-2 sm:grid-cols-2">
                          {resourcesByKind[kind].map((resource) => {
                            const silence = activeSilence(resource);
                            return <div className="flex min-h-12 items-center justify-between gap-2 rounded-md bg-muted/35 px-3" key={resource.key}><div className="min-w-0"><p className="truncate font-mono text-xs" title={resource.key}>{resource.key.replace(`${kind}:`, "")}</p><p className={cn("text-[11px]", resource.ok ? "text-success" : "text-warning")}>{resource.ok ? "Healthy" : resource.summary}</p></div>{silence ? <Button aria-label={`Remove silence for ${resource.key}`} className="h-9 min-h-9 gap-1 px-2" onClick={() => void savePolicy({ ...status.policy, silences: status.policy.silences.filter((item) => item.key !== resource.key) }, `${resource.key} unsilenced.`)} title="Remove silence" variant="warning"><Clock3 className="h-3.5 w-3.5" /><X className="h-3.5 w-3.5" /></Button> : <Button aria-label={`Silence ${resource.key}`} className="h-9 min-h-9 px-2" onClick={() => setSilenceDraft({ resource, duration: "1h", reason: "" })} title="Silence resource" variant="ghost"><BellRing className="h-4 w-4" /></Button>}</div>;
                          })}
                        </div> : <p className="mt-2 text-xs text-dim">No resources discovered yet.</p>}
                      </div>;
                    })}
                  </div>
                  <div className="space-y-2 border-t border-border pt-5">
                    <label className="block space-y-1"><span className="font-mono text-xs font-semibold">Required mountpoints</span><input className={FIELD_CLASS} onChange={(event) => setMountDraft(event.target.value)} placeholder="/mnt/media, /mnt/parity" value={mountDraft} /></label>
                    <div className="flex justify-end"><Button disabled={savingPolicy} onClick={() => void savePolicy({ ...status.policy, required_mounts: mountDraft.split(",").map((item) => item.trim()).filter(Boolean) })} size="sm">Save mounts</Button></div>
                  </div>
                </div>
              ) : null}

            </CardContent>
          </>
        ) : (
          <CardContent className="p-4 sm:p-6">
            <div className="grid gap-4 sm:grid-cols-3">
              {[ [ServerCog, "One managed stack", "Postgres, Mattermost, and alerts install together."], [ShieldAlert, "Clear alert controls", "Enable categories and silence individual resources."], [Bot, "Agent-ready", "The same channel will support guided investigations."] ].map(([Icon, title, copy]) => { const ItemIcon = Icon as typeof ServerCog; return <div className="border-l border-border pl-3" key={title as string}><ItemIcon className="mb-2 h-4 w-4 text-primary" /><p className="text-sm font-medium">{title as string}</p><p className="mt-1 text-xs text-muted-foreground">{copy as string}</p></div>; })}
            </div>
          </CardContent>
        )}
      </Card>

      <AgentsIntegrationCard onLifecycleChanged={invalidateIntegrations} refreshKey={integrationRefreshKey} />

      <StackNotificationsCard refreshKey={integrationRefreshKey} />

      <PackageUpdatesCard refreshKey={integrationRefreshKey} />

      {setupOpen ? <ModalOverlay onClose={installing ? () => undefined : () => setSetupOpen(false)} restoreFocus={() => document.getElementById("mattermost-integration")?.focus()}><Card aria-labelledby="mattermost-setup-title" aria-modal="true" className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden" role="dialog"><CardHeader className="flex flex-row items-start justify-between border-b border-border"><div><CardTitle id="mattermost-setup-title">Set up Mattermost</CardTitle><CardDescription>Install chat and connect LimeOS alerts in one workflow.</CardDescription></div><Button aria-label="Close setup" className="w-11 px-0" disabled={installing} onClick={() => setSetupOpen(false)} variant="ghost"><X className="h-4 w-4" /></Button></CardHeader><CardContent className="space-y-4 overflow-auto p-4 sm:p-6">
        {installing || installLines.length ? <div className="space-y-3"><div className={cn("flex items-center gap-2 text-sm", error ? "text-danger" : "text-info")}>{installing ? <Loader2 className="h-4 w-4 animate-spin" /> : error ? <TriangleAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}{installing ? "Installing Mattermost" : error ? "Setup failed" : "Setup finished"}</div><pre className="max-h-72 overflow-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground" data-mattermost-install-log>{installLines.join("\n")}</pre>{!installing ? <Button onClick={() => setSetupOpen(false)}>Close</Button> : null}</div> : <>
          <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 sm:col-span-2"><span className="text-xs text-muted-foreground">Mattermost URL</span><input className={FIELD_CLASS} onChange={(event) => setSetup({ ...setup, site_url: event.target.value })} value={setup.site_url} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Admin username</span><input autoComplete="username" className={FIELD_CLASS} onChange={(event) => setSetup({ ...setup, admin_username: event.target.value })} value={setup.admin_username} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Admin email</span><input autoComplete="email" className={FIELD_CLASS} onChange={(event) => setSetup({ ...setup, admin_email: event.target.value })} type="email" value={setup.admin_email} /></label><label className="space-y-1 sm:col-span-2"><span className="text-xs text-muted-foreground">Admin password</span><input autoComplete="new-password" className={FIELD_CLASS} minLength={10} onChange={(event) => setSetup({ ...setup, admin_password: event.target.value })} type="password" value={setup.admin_password} /></label></div>
          <button className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground hover:text-foreground" onClick={() => setAdvanced((value) => !value)} type="button"><ServerCog className="h-4 w-4" />Advanced settings</button>
          {advanced ? <div className="grid gap-3 border-l border-border pl-3 sm:grid-cols-2"><label className="space-y-1"><span className="text-xs text-muted-foreground">Stack name</span><input className={FIELD_CLASS} onChange={(event) => setSetup({ ...setup, stack_name: event.target.value })} value={setup.stack_name} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Channel</span><input className={FIELD_CLASS} onChange={(event) => setSetup({ ...setup, channel_name: event.target.value })} value={setup.channel_name} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Poll interval (seconds)</span><input className={FIELD_CLASS} min={15} onChange={(event) => setSetup({ ...setup, poll_seconds: Number(event.target.value) })} type="number" value={setup.poll_seconds} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Failures before alerting</span><input className={FIELD_CLASS} min={1} onChange={(event) => setSetup({ ...setup, fail_threshold: Number(event.target.value) })} type="number" value={setup.fail_threshold} /></label></div> : null}
          <Button className="w-full gap-2 sm:w-auto" data-mattermost-install disabled={!setup.admin_email || setup.admin_password.length < 10} onClick={() => void runInstall()}><MessageSquare className="h-4 w-4" />Install and connect</Button>
        </>}
      </CardContent></Card></ModalOverlay> : null}

      {blockedAction ? (
        <ModalOverlay onClose={() => setBlockedAction(null)} restoreFocus={() => document.getElementById("mattermost-integration")?.focus()}>
          <Card aria-labelledby="mattermost-blocked-title" aria-modal="true" className="w-full max-w-lg" role="dialog">
            <CardHeader className="flex flex-row items-start justify-between border-b border-border">
              <div><CardTitle id="mattermost-blocked-title">{blockedAction.action === "disable" ? "Disable" : "Uninstall"} AI Agents first</CardTitle><CardDescription>Mattermost is required by the installed assistant integration.</CardDescription></div>
              <Button aria-label="Close dependency notice" className="h-11 w-11 shrink-0 px-0" onClick={() => setBlockedAction(null)} variant="ghost"><X className="h-4 w-4" /></Button>
            </CardHeader>
            <CardContent className="space-y-4 p-4 sm:p-5">
              <div className="flex items-start gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3"><Bot className="mt-0.5 h-4 w-4 shrink-0 text-warning" /><div><p className="text-sm font-medium">AI Agents blocks this action</p><p className="mt-1 text-sm text-muted-foreground">{blockedAction.message}</p></div></div>
              <div className="flex flex-wrap justify-end gap-2"><Button onClick={() => setBlockedAction(null)} variant="outline">Cancel</Button><Button className="gap-2" data-mattermost-go-to-agents onClick={() => focusBlockedDependency(blockedAction)}><Bot className="h-4 w-4" />Go to AI Agents</Button></div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {lifecycle.state.open && lifecycleMode ? (
        <IntegrationLifecycleDialog
          acknowledgement={purgeMode ? "I understand this permanently deletes all retained Mattermost data and cannot be undone." : undefined}
          confirmLabel={lifecycleMode === "disable" ? "Disable Mattermost" : lifecycleMode === "enable" ? "Enable Mattermost" : lifecycleMode === "uninstall" ? "Uninstall Mattermost" : lifecycleMode === "purge" ? "Delete all data" : lifecycleMode === "retry_disable" ? "Retry disable" : lifecycleMode === "retry_enable" ? "Retry enable" : lifecycleMode === "retry_uninstall" ? "Retry uninstall" : "Retry data deletion"}
          confirmation={destructiveMode ? { expected: "Mattermost" } : undefined}
          description={purgeMode ? "Permanently delete retained Mattermost data after the services have been uninstalled." : lifecycleMode === "uninstall" || lifecycleMode === "retry_uninstall" ? "Remove the managed Mattermost stack and alert delivery while retaining chat data for reinstall." : lifecycleMode === "disable" || lifecycleMode === "retry_disable" ? "Stop the complete Mattermost stack and alert delivery while preserving configuration and data." : "Start the complete Mattermost stack and restore alert delivery."}
          destructive={destructiveMode}
          onClose={closeLifecycle}
          onConfirm={(values) => void runLifecycle(values.confirmation, values.acknowledged)}
          onRetry={retryLifecycle}
          restoreFocus={() => document.getElementById("mattermost-integration")?.focus()}
          state={lifecycle.state}
          title={lifecycleMode === "disable" ? "Disable Mattermost?" : lifecycleMode === "enable" ? "Enable Mattermost?" : lifecycleMode === "uninstall" ? "Uninstall Mattermost?" : lifecycleMode === "purge" ? "Delete retained Mattermost data?" : lifecycleMode === "retry_disable" ? "Retry Mattermost disable" : lifecycleMode === "retry_enable" ? "Retry Mattermost enable" : lifecycleMode === "retry_uninstall" ? "Retry Mattermost uninstall" : "Retry Mattermost data deletion"}
        >
          {lifecycleMode === "uninstall" || lifecycleMode === "retry_uninstall" ? (
            <div className="grid gap-3 text-sm sm:grid-cols-2">
              <div className="border-l-2 border-danger/60 pl-3"><p className="font-medium text-danger">Removed</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Mattermost, Postgres, and alert containers; alert delivery; and LimeOS connection configuration.</p></div>
              <div className="border-l-2 border-success/60 pl-3"><p className="font-medium text-success">Preserved</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Database records, messages, uploads, plugins, and retained logs for a future reinstall.</p></div>
            </div>
          ) : null}
          {purgeMode ? (
            <div className="border-l-2 border-danger bg-danger/5 px-3 py-2 text-sm text-muted-foreground">This permanently removes database records, messages, uploads, plugins, retained logs, and recovery metadata.</div>
          ) : null}
        </IntegrationLifecycleDialog>
      ) : null}

      {silenceDraft ? <ModalOverlay onClose={() => setSilenceDraft(null)}><Card aria-labelledby="mattermost-silence-title" aria-modal="true" className="w-full max-w-md" role="dialog"><CardHeader><CardTitle id="mattermost-silence-title">Silence {silenceDraft.resource.key}</CardTitle><CardDescription>Alerts remain visible in LimeOS while Mattermost delivery is paused.</CardDescription></CardHeader><CardContent className="space-y-3"><label className="block space-y-1"><span className="text-xs text-muted-foreground">Duration</span><select className={FIELD_CLASS} onChange={(event) => setSilenceDraft({ ...silenceDraft, duration: event.target.value as SilenceDraft["duration"] })} value={silenceDraft.duration}><option value="1h">1 hour</option><option value="24h">24 hours</option><option value="permanent">Until manually removed</option></select></label><label className="block space-y-1"><span className="text-xs text-muted-foreground">Reason (optional)</span><input className={FIELD_CLASS} maxLength={200} onChange={(event) => setSilenceDraft({ ...silenceDraft, reason: event.target.value })} value={silenceDraft.reason} /></label><div className="flex justify-end gap-2"><Button onClick={() => setSilenceDraft(null)} variant="ghost">Cancel</Button><Button className="gap-2" onClick={confirmSilence} variant="warning"><BellRing className="h-4 w-4" />Silence</Button></div></CardContent></Card></ModalOverlay> : null}
    </section>
  );
}
