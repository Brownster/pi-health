import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Ban,
  Bot,
  CheckCircle2,
  Clock3,
  ExternalLink,
  KeyRound,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  TerminalSquare,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  cancelClaudeAuth,
  disableAgents,
  getAgentAudit,
  getAgentPermissions,
  getAgentProviders,
  getAgentStatus,
  getAgentUsage,
  installAgents,
  repairAgents,
  sendAgentTest,
  startClaudeAuth,
  streamClaudeAuth,
  submitClaudeAuth,
  type AgentAudit,
  type AgentInstallValues,
  type AgentPermissions,
  type AgentProvider,
  type AgentState,
  type AgentStatus,
  type AgentUsage,
} from "@/lib/agents";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

type AgentTab = "overview" | "providers" | "permissions" | "usage" | "audit";
type OperationMode = "install" | "repair";

const TABS: Array<{ id: AgentTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "providers", label: "Providers" },
  { id: "permissions", label: "Permissions" },
  { id: "usage", label: "Usage" },
  { id: "audit", label: "Audit" },
];

const EMPTY_INSTALL: AgentInstallValues = {
  admin_username: "limeadmin",
  admin_password: "",
  limits: {
    turn_timeout_seconds: 300,
    tool_rounds_per_turn: 6,
    invocations_per_day: 20,
  },
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed";
}

function formatTime(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function formatDuration(value?: number): string {
  if (value === undefined) return "-";
  return value < 1 ? `${Math.round(value * 1000)} ms` : `${value.toFixed(1)} s`;
}

function stateTone(state: AgentState): "success" | "warning" | "danger" | "neutral" | "info" {
  if (state === "connected") return "success";
  if (state === "authenticating") return "info";
  if (state === "setup_required" || state === "degraded") return "warning";
  if (state === "disconnected") return "danger";
  return "neutral";
}

function displayState(state: AgentState): string {
  return state.replace(/_/g, " ");
}

function operationLabel(operation: string): string {
  return operation.replace(".", " / ");
}

export function AgentsIntegrationCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<AgentTab>("overview");
  const [providers, setProviders] = useState<AgentProvider[] | null>(null);
  const [permissions, setPermissions] = useState<AgentPermissions | null>(null);
  const [usage, setUsage] = useState<AgentUsage | null>(null);
  const [audit, setAudit] = useState<AgentAudit | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [operationMode, setOperationMode] = useState<OperationMode | null>(null);
  const [operationRunning, setOperationRunning] = useState(false);
  const [operationLines, setOperationLines] = useState<string[]>([]);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [requiresAuth, setRequiresAuth] = useState(false);
  const [finishSetup, setFinishSetup] = useState(false);
  const [installValues, setInstallValues] = useState<AgentInstallValues>(EMPTY_INSTALL);
  const [repairMattermost, setRepairMattermost] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [authRunning, setAuthRunning] = useState(false);
  const [authOperationId, setAuthOperationId] = useState<string | null>(null);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [authCode, setAuthCode] = useState("");
  const [authNeedsInput, setAuthNeedsInput] = useState(false);
  const [authLines, setAuthLines] = useState<string[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authComplete, setAuthComplete] = useState(false);
  const [authRequiresSetup, setAuthRequiresSetup] = useState(false);
  const [submittingAuth, setSubmittingAuth] = useState(false);
  const [testing, setTesting] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const authAbortRef = useRef<AbortController | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const next = await getAgentStatus();
      setStatus(next);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus, refreshKey]);

  useEffect(() => {
    if (!status?.installed || tab === "overview") return;
    const controller = new AbortController();
    setDetailLoading(true);
    const request =
      tab === "providers"
        ? getAgentProviders(controller.signal).then((result) => setProviders(result.providers))
        : tab === "permissions"
          ? getAgentPermissions(controller.signal).then(setPermissions)
          : tab === "usage"
            ? getAgentUsage(50, controller.signal).then(setUsage)
            : getAgentAudit(50, controller.signal).then(setAudit);
    void request
      .then(() => setError(null))
      .catch((caught) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(errorMessage(caught));
        }
      })
      .finally(() => setDetailLoading(false));
    return () => controller.abort();
  }, [status?.installed, tab]);

  function openOperation(mode: OperationMode, configureMattermost = false) {
    setOperationMode(mode);
    setOperationLines([]);
    setOperationError(null);
    setRequiresAuth(false);
    setFinishSetup(mode === "repair" && configureMattermost);
    setRepairMattermost(configureMattermost);
  }

  function closeOperation() {
    setInstallValues((current) => ({ ...current, admin_password: "" }));
    setRepairMattermost(false);
    setFinishSetup(false);
    setOperationMode(null);
  }

  async function runOperation() {
    if (!operationMode) return;
    setOperationRunning(true);
    setOperationError(null);
    setRequiresAuth(false);
    setOperationLines([
      operationMode === "install" ? "Starting AI Agents setup" : "Starting AI Agents repair",
    ]);
    let operationRequiresAuth = false;
    try {
      const onEvent = (event: { line?: string; error?: string; requires_auth?: boolean }) => {
        if (event.line) setOperationLines((current) => [...current, event.line as string]);
        if (event.requires_auth) {
          operationRequiresAuth = true;
          setRequiresAuth(true);
        }
        if (event.error) {
          setOperationError(event.error);
          throw new Error(event.error);
        }
      };
      if (operationMode === "install") {
        await installAgents(installValues, onEvent);
      } else {
        await repairAgents(
          repairMattermost
            ? {
                admin_username: installValues.admin_username,
                admin_password: installValues.admin_password,
              }
            : {},
          onEvent,
        );
      }
      await loadStatus();
      setNotice(
        operationRequiresAuth
          ? "AI Agents is installed. Connect Claude to finish setup."
          : `AI Agents ${operationMode === "install" ? "setup" : "repair"} completed.`,
      );
    } catch (caught) {
      setOperationError(errorMessage(caught));
    } finally {
      setInstallValues((current) => ({ ...current, admin_password: "" }));
      setOperationRunning(false);
    }
  }

  function resetAuthState() {
    setAuthOperationId(null);
    setAuthUrl(null);
    setAuthCode("");
    setAuthNeedsInput(false);
    setAuthLines([]);
    setAuthError(null);
    setAuthComplete(false);
    setAuthRequiresSetup(false);
  }

  async function beginAuth() {
    resetAuthState();
    setAuthOpen(true);
    setAuthRunning(true);
    const controller = new AbortController();
    authAbortRef.current = controller;
    let setupRequired = false;
    try {
      const operation = await startClaudeAuth(controller.signal);
      await streamClaudeAuth(
        operation.stream_url,
        (event) => {
          if (event.operation_id) setAuthOperationId(event.operation_id);
          if (event.authorization_url) setAuthUrl(event.authorization_url);
          if (event.step === "input_required") setAuthNeedsInput(true);
          if (event.line) setAuthLines((current) => [...current, event.line as string]);
          if (event.error) {
            setAuthUrl(null);
            setAuthError(event.error);
            throw new Error(event.error);
          }
          if (event.done) {
            setAuthUrl(null);
            setAuthComplete(true);
            if (event.requires_setup) {
              setupRequired = true;
              setAuthRequiresSetup(true);
            }
          }
        },
        controller.signal,
      );
      setNotice(
        setupRequired
          ? "Claude is connected. Finish assistant setup to enable @limeos."
          : "Claude is connected to the LimeOS assistant.",
      );
      await loadStatus();
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setAuthError(errorMessage(caught));
      }
    } finally {
      setAuthUrl(null);
      setAuthRunning(false);
      authAbortRef.current = null;
    }
  }

  async function submitAuth() {
    if (!authOperationId || !authCode.trim()) return;
    setSubmittingAuth(true);
    try {
      await submitClaudeAuth(authOperationId, authCode.trim());
      setAuthCode("");
      setAuthNeedsInput(false);
      setAuthLines((current) => [...current, "Authorization response submitted"]);
    } catch (caught) {
      setAuthError(errorMessage(caught));
    } finally {
      setSubmittingAuth(false);
    }
  }

  async function closeAuth() {
    const operationId = authOperationId;
    authAbortRef.current?.abort();
    authAbortRef.current = null;
    setAuthUrl(null);
    setAuthOpen(false);
    if (authRunning && operationId) {
      await cancelClaudeAuth(operationId).catch(() => undefined);
    }
    setAuthRunning(false);
    resetAuthState();
  }

  async function testDelivery() {
    setTesting(true);
    try {
      await sendAgentTest();
      setNotice("Assistant test delivered to the Mattermost alerts channel.");
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setTesting(false);
    }
  }

  async function disable() {
    setDisabling(true);
    try {
      await disableAgents();
      setDisableOpen(false);
      setNotice("AI Agents is disabled. Mattermost and alert delivery remain active.");
      await loadStatus();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setDisabling(false);
    }
  }

  const mattermostReady = ["connected", "degraded"].includes(status?.mattermost.state ?? "");
  const needsProviderAuth = Boolean(status?.installed && !status.provider.authenticated);
  const needsConfiguration = Boolean(status?.installed && !status.configured);

  return (
    <>
      {notice ? (
        <div className="flex items-center justify-between gap-3 border-l-2 border-success bg-success/5 px-4 py-3 text-sm text-success" role="status">
          <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 shrink-0" />{notice}</span>
          <Button aria-label="Dismiss agent notice" className="h-9 min-h-9 w-9 px-0" onClick={() => setNotice(null)} variant="ghost"><X className="h-4 w-4" /></Button>
        </div>
      ) : null}
      {error ? (
        <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-4 py-3 text-sm text-danger" role="alert">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}
        </div>
      ) : null}

      <Card className="overflow-hidden" data-agent-integration>
        <CardHeader className="border-b border-border/70 bg-muted/20">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary">
                <Bot className="h-5 w-5" />
              </span>
              <div>
                <CardTitle>AI Agents</CardTitle>
                <CardDescription>Provider-neutral assistance for Mattermost investigations</CardDescription>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge label={status ? displayState(status.state) : loading ? "loading" : "unavailable"} tone={status ? stateTone(status.state) : "neutral"} />
              {!status?.installed ? (
                <Button className="gap-2" data-agent-setup disabled={!mattermostReady || loading} onClick={() => openOperation("install")}>
                  <Plus className="h-4 w-4" />Set up
                </Button>
              ) : null}
            </div>
          </div>
        </CardHeader>

        {status?.installed ? (
          <>
            <div className="flex overflow-x-auto border-b border-border px-2 sm:px-4" role="tablist" aria-label="AI Agents views">
              {TABS.map((item) => (
                <button
                  aria-selected={tab === item.id}
                  className={cn(
                    "min-h-11 shrink-0 cursor-pointer border-b-2 px-3 font-mono text-xs transition-colors sm:px-4",
                    tab === item.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                  key={item.id}
                  onClick={() => setTab(item.id)}
                  role="tab"
                  type="button"
                >{item.label}</button>
              ))}
            </div>
            <CardContent className="p-4 sm:p-6">
              {detailLoading ? <div className="flex min-h-36 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-primary" aria-label="Loading agent details" /></div> : null}
              {!detailLoading && tab === "overview" ? (
                <div className="space-y-5">
                  <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 xl:grid-cols-5">
                    {[
                      ["Identity", "@limeos"],
                      ["Channel", `~${status.mattermost.channel ?? "unknown"}`],
                      ["Gateway", status.gateway.state],
                      ["Broker", status.gateway.broker_state],
                      ["Last turn", formatTime(status.last_successful_turn?.at)],
                    ].map(([label, value]) => (
                      <div className="min-w-0 bg-card p-3" key={label}>
                        <p className="font-mono text-[10px] uppercase text-dim">{label}</p>
                        <p className="mt-1 truncate text-sm" title={value}>{value}</p>
                      </div>
                    ))}
                  </div>
                  {status.state !== "connected" ? (
                    <div className={cn("flex items-start gap-3 border-l-2 px-4 py-3", status.state === "disconnected" ? "border-danger bg-danger/5" : "border-warning bg-warning/5")}>
                      <TriangleAlert className={cn("mt-0.5 h-4 w-4 shrink-0", status.state === "disconnected" ? "text-danger" : "text-warning")} />
                      <div><p className="text-sm font-medium">{status.state === "disabled" ? "Assistant disabled" : status.state === "setup_required" ? "Setup needs attention" : "Assistant connection needs attention"}</p><p className="text-xs text-muted-foreground">Mattermost alerts continue independently while the assistant is unavailable.</p></div>
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    {needsProviderAuth ? <Button className="gap-2" onClick={() => void beginAuth()} variant="info"><KeyRound className="h-4 w-4" />Authenticate Claude</Button> : null}
                    {status.state === "connected" ? <Button className="gap-2" disabled={testing} onClick={() => void testDelivery()} variant="info">{testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}{testing ? "Sending" : "Test assistant"}</Button> : null}
                    <Button className="gap-2" onClick={() => openOperation("repair", needsConfiguration)} variant="secondary"><Wrench className="h-4 w-4" />{needsConfiguration ? "Finish setup" : status.state === "disabled" ? "Enable and repair" : "Repair"}</Button>
                    {status.state !== "disabled" ? <Button className="gap-2" onClick={() => setDisableOpen(true)} variant="danger"><Ban className="h-4 w-4" />Disable</Button> : null}
                    {status.mattermost.site_url ? <a className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border px-4 font-mono text-sm transition-colors hover:bg-muted" href={status.mattermost.site_url} rel="noreferrer" target="_blank">Open Mattermost<ExternalLink className="h-4 w-4" /></a> : null}
                  </div>
                </div>
              ) : null}

              {!detailLoading && tab === "providers" ? <ProvidersView providers={providers ?? []} onAuthenticate={() => void beginAuth()} /> : null}
              {!detailLoading && tab === "permissions" ? <PermissionsView permissions={permissions} /> : null}
              {!detailLoading && tab === "usage" ? <UsageView usage={usage} /> : null}
              {!detailLoading && tab === "audit" ? <AuditView audit={audit} /> : null}
            </CardContent>
          </>
        ) : (
          <CardContent className="p-4 sm:p-6">
            {!mattermostReady && status ? (
              <div className="mb-5 flex items-start gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3">
                <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div><p className="text-sm font-medium">Connect Mattermost first</p><p className="text-xs text-muted-foreground">AI Agents uses the existing LimeOS team and alerts channel.</p></div>
              </div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                [Bot, "One assistant identity", "Mention @limeos without exposing the selected provider."],
                [ShieldCheck, "Read-only by default", "Host diagnostics pass through fixed LimeOps permissions."],
                [TerminalSquare, "Claude Code first", "Use an existing Claude subscription through guided authentication."],
              ].map(([Icon, title, copy]) => {
                const ItemIcon = Icon as typeof Bot;
                return <div className="border-l border-border pl-3" key={title as string}><ItemIcon className="mb-2 h-4 w-4 text-primary" /><p className="text-sm font-medium">{title as string}</p><p className="mt-1 text-xs text-muted-foreground">{copy as string}</p></div>;
              })}
            </div>
          </CardContent>
        )}
      </Card>

      {operationMode ? (
        <ModalOverlay onClose={operationRunning ? () => undefined : closeOperation}>
          <Card aria-labelledby="agent-operation-title" aria-modal="true" className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden" role="dialog">
            <CardHeader className="flex flex-row items-start justify-between border-b border-border">
              <div><CardTitle id="agent-operation-title">{operationMode === "install" ? "Set up AI Agents" : finishSetup ? "Finish AI Agents setup" : "Repair AI Agents"}</CardTitle><CardDescription>{operationMode === "install" ? "Connect @limeos to Mattermost with Claude Code and read-only host access." : finishSetup ? "Create the missing Mattermost bot configuration and start the assistant." : "Reinstall the provider and isolated runtime while preserving agent data."}</CardDescription></div>
              <Button aria-label="Close agent setup" className="w-11 px-0" disabled={operationRunning} onClick={closeOperation} variant="ghost"><X className="h-4 w-4" /></Button>
            </CardHeader>
            <CardContent className="space-y-4 overflow-auto p-4 sm:p-6">
              {operationRunning || operationLines.length ? (
                <div className="space-y-3">
                  <div className={cn("flex items-center gap-2 text-sm", operationError ? "text-danger" : operationRunning ? "text-info" : "text-success")}>{operationRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : operationError ? <TriangleAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}{operationRunning ? operationMode === "install" ? "Installing AI Agents" : "Repairing AI Agents" : operationError ? "Operation failed" : "Operation finished"}</div>
                  <pre className="max-h-72 overflow-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground" data-agent-operation-log>{operationLines.join("\n")}{operationError ? `\n${operationError}` : ""}</pre>
                  {!operationRunning ? <div className="flex flex-wrap gap-2">{requiresAuth && !operationError ? <Button className="gap-2" onClick={() => { closeOperation(); void beginAuth(); }} variant="info"><KeyRound className="h-4 w-4" />Authenticate Claude</Button> : null}<Button onClick={closeOperation} variant={requiresAuth ? "secondary" : "default"}>Close</Button></div> : null}
                </div>
              ) : operationMode === "install" ? (
                <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="space-y-1"><span className="text-xs text-muted-foreground">Mattermost admin username</span><input autoComplete="username" className={FIELD_CLASS} onChange={(event) => setInstallValues({ ...installValues, admin_username: event.target.value })} value={installValues.admin_username} /></label>
                    <label className="space-y-1"><span className="text-xs text-muted-foreground">Mattermost admin password</span><input autoComplete="current-password" className={FIELD_CLASS} minLength={10} onChange={(event) => setInstallValues({ ...installValues, admin_password: event.target.value })} type="password" value={installValues.admin_password} /></label>
                  </div>
                  <button className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-muted-foreground hover:text-foreground" onClick={() => setAdvanced((value) => !value)} type="button"><Activity className="h-4 w-4" />Usage limits</button>
                  {advanced && installValues.limits ? <div className="grid gap-3 border-l border-border pl-3 sm:grid-cols-3"><label className="space-y-1"><span className="text-xs text-muted-foreground">Turn timeout</span><input className={FIELD_CLASS} max={600} min={10} onChange={(event) => setInstallValues({ ...installValues, limits: { ...installValues.limits!, turn_timeout_seconds: Number(event.target.value) } })} type="number" value={installValues.limits.turn_timeout_seconds} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Tool rounds</span><input className={FIELD_CLASS} max={10} min={1} onChange={(event) => setInstallValues({ ...installValues, limits: { ...installValues.limits!, tool_rounds_per_turn: Number(event.target.value) } })} type="number" value={installValues.limits.tool_rounds_per_turn} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Daily invocations</span><input className={FIELD_CLASS} max={1000} min={1} onChange={(event) => setInstallValues({ ...installValues, limits: { ...installValues.limits!, invocations_per_day: Number(event.target.value) } })} type="number" value={installValues.limits.invocations_per_day} /></label></div> : null}
                  <Button className="gap-2" data-agent-install disabled={!installValues.admin_username || installValues.admin_password.length < 10} onClick={() => void runOperation()}><Bot className="h-4 w-4" />Install assistant</Button>
                </>
              ) : <><div className="flex items-start gap-3 border-l-2 border-info bg-info/5 px-4 py-3"><RefreshCw className="mt-0.5 h-4 w-4 shrink-0 text-info" /><p className="text-sm text-muted-foreground">Provider binaries and system services will be verified and repaired. Conversations, usage, audit records, and Mattermost alerts are preserved.</p></div><label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm"><input checked={repairMattermost} className="h-4 w-4 accent-primary" onChange={(event) => setRepairMattermost(event.target.checked)} type="checkbox" /><span><span className="block font-medium">Repair Mattermost bot and configuration</span><span className="block text-xs text-muted-foreground">Use this after an interrupted setup or missing bot configuration.</span></span></label>{repairMattermost ? <div className="grid gap-3 border-l border-border pl-3 sm:grid-cols-2"><label className="space-y-1"><span className="text-xs text-muted-foreground">Mattermost admin username</span><input autoComplete="username" className={FIELD_CLASS} onChange={(event) => setInstallValues({ ...installValues, admin_username: event.target.value })} value={installValues.admin_username} /></label><label className="space-y-1"><span className="text-xs text-muted-foreground">Mattermost admin password</span><input autoComplete="current-password" className={FIELD_CLASS} minLength={10} onChange={(event) => setInstallValues({ ...installValues, admin_password: event.target.value })} type="password" value={installValues.admin_password} /></label></div> : null}<Button className="gap-2" data-agent-repair disabled={repairMattermost && (!installValues.admin_username || installValues.admin_password.length < 10)} onClick={() => void runOperation()}><Wrench className="h-4 w-4" />{finishSetup ? "Finish setup" : "Start repair"}</Button></>}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {authOpen ? (
        <ModalOverlay onClose={() => void closeAuth()}>
          <Card aria-labelledby="claude-auth-title" aria-modal="true" className="flex max-h-[92vh] w-full max-w-xl flex-col overflow-hidden" role="dialog">
            <CardHeader className="flex flex-row items-start justify-between border-b border-border"><div><CardTitle id="claude-auth-title">Connect Claude Code</CardTitle><CardDescription>Authorize the LimeOS assistant with your Claude subscription.</CardDescription></div><Button aria-label="Close Claude authentication" className="w-11 px-0" onClick={() => void closeAuth()} variant="ghost"><X className="h-4 w-4" /></Button></CardHeader>
            <CardContent className="space-y-4 overflow-auto p-4 sm:p-6">
              <div className={cn("flex items-center gap-2 text-sm", authError ? "text-danger" : authComplete ? "text-success" : "text-info")}>{authRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : authError ? <TriangleAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}{authRunning ? "Waiting for Claude authorization" : authError ? "Authentication failed" : authComplete ? "Claude connected" : "Preparing authentication"}</div>
              {authUrl ? <a className="flex min-h-11 items-center justify-center gap-2 rounded-md border border-info/30 bg-info/10 px-4 font-mono text-sm text-info transition-colors hover:bg-info/15" href={authUrl} rel="noreferrer" target="_blank">Open Claude authorization<ExternalLink className="h-4 w-4" /></a> : null}
              {authNeedsInput ? <div className="space-y-2"><label className="block space-y-1"><span className="text-xs text-muted-foreground">Authorization response</span><textarea className={cn(FIELD_CLASS, "min-h-24 resize-y")} onChange={(event) => setAuthCode(event.target.value)} value={authCode} /></label><Button className="gap-2" disabled={!authCode.trim() || submittingAuth} onClick={() => void submitAuth()}>{submittingAuth ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}Submit response</Button></div> : null}
              {authLines.length || authError ? <pre className="max-h-48 overflow-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground" data-agent-auth-log>{authLines.join("\n")}{authError ? `\n${authError}` : ""}</pre> : null}
              {!authRunning ? <div className="flex flex-wrap gap-2">{authComplete && authRequiresSetup ? <Button className="gap-2" onClick={() => { void closeAuth().then(() => openOperation("repair", true)); }}><Wrench className="h-4 w-4" />Finish setup</Button> : null}<Button onClick={() => void closeAuth()} variant={authRequiresSetup ? "secondary" : "default"}>{authComplete ? "Done" : "Close"}</Button></div> : null}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {disableOpen ? <ModalOverlay onClose={disabling ? () => undefined : () => setDisableOpen(false)}><Card aria-labelledby="disable-agent-title" aria-modal="true" className="w-full max-w-md" role="dialog"><CardHeader><CardTitle id="disable-agent-title">Disable AI Agents?</CardTitle><CardDescription>The assistant stops immediately. Mattermost, alerts, conversations, usage, and audit history stay in place.</CardDescription></CardHeader><CardContent className="flex justify-end gap-2"><Button disabled={disabling} onClick={() => setDisableOpen(false)} variant="ghost">Cancel</Button><Button className="gap-2" disabled={disabling} onClick={() => void disable()} variant="danger">{disabling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />}Disable assistant</Button></CardContent></Card></ModalOverlay> : null}
    </>
  );
}

function ProvidersView({ providers, onAuthenticate }: { providers: AgentProvider[]; onAuthenticate: () => void }) {
  return <div className="space-y-4"><div><h3 className="font-mono text-sm font-semibold">Providers</h3><p className="text-xs text-muted-foreground">The @limeos identity stays the same when providers change.</p></div><div className="divide-y divide-border rounded-md border border-border">{providers.map((provider) => <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between" key={provider.id}><div className="flex items-start gap-3"><TerminalSquare className="mt-0.5 h-5 w-5 text-info" /><div><p className="text-sm font-medium">{provider.name}</p><p className="text-xs text-muted-foreground">{provider.installed ? `Version ${provider.version ?? "unknown"}` : "Not installed"}</p><div className="mt-2 flex flex-wrap gap-2"><Badge tone={provider.compatible ? "success" : "warning"}>{provider.compatible ? "Compatible" : "Compatibility required"}</Badge><Badge tone={provider.authenticated ? "success" : "neutral"}>{provider.authenticated ? "Authenticated" : "Authentication required"}</Badge></div></div></div>{!provider.authenticated ? <Button className="gap-2 self-start" onClick={onAuthenticate} variant="info"><KeyRound className="h-4 w-4" />Authenticate</Button> : null}</div>)}</div></div>;
}

function PermissionsView({ permissions }: { permissions: AgentPermissions | null }) {
  if (!permissions) return <EmptyState icon={ShieldCheck} text="Permission data is unavailable." />;
  return <div className="space-y-5"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><h3 className="font-mono text-sm font-semibold">Read-only permissions</h3><p className="text-xs text-muted-foreground">Enforced by LimeOps independently of Claude.</p></div><Badge tone="success"><ShieldCheck className="h-3.5 w-3.5" />{permissions.profile.replace("_", " ")}</Badge></div><div className="divide-y divide-border rounded-md border border-border">{permissions.allowed_operations.map((operation) => <div className="grid gap-2 p-3 sm:grid-cols-[minmax(10rem,0.7fr)_1fr] sm:items-center" key={operation}><code className="text-xs text-foreground">{operationLabel(operation)}</code><div className="flex flex-wrap gap-1.5">{permissions.resources[operation]?.length ? permissions.resources[operation].map((resource) => <Badge key={resource}>{resource}</Badge>) : <span className="text-xs text-dim">No resource restriction</span>}</div></div>)}</div><div><h4 className="mb-2 font-mono text-xs font-semibold text-muted-foreground">Explicitly denied</h4><div className="flex flex-wrap gap-2">{permissions.denied_capabilities.map((capability) => <Badge key={capability} tone="danger">{capability}</Badge>)}</div></div></div>;
}

function UsageView({ usage }: { usage: AgentUsage | null }) {
  if (!usage) return <EmptyState icon={Activity} text="No usage data is available yet." />;
  return <div className="space-y-5"><div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-3">{[["Turns", usage.totals.total_turns ?? 0], ["Provider calls", usage.totals.total_invocations ?? 0], ["Calls today", usage.totals.invocations_today ?? 0]].map(([label, value]) => <div className="bg-card p-4" key={label}><p className="font-mono text-[10px] uppercase text-dim">{label}</p><p className="mt-1 font-mono text-xl">{value}</p></div>)}</div>{usage.records.length ? <div className="overflow-x-auto rounded-md border border-border"><table className="w-full min-w-[640px] text-left text-xs"><thead className="border-b border-border bg-muted/30 font-mono text-dim"><tr><th className="p-3 font-medium">Time</th><th className="p-3 font-medium">Outcome</th><th className="p-3 font-medium">Rounds</th><th className="p-3 font-medium">Duration</th><th className="p-3 font-medium">Tools</th></tr></thead><tbody className="divide-y divide-border">{usage.records.map((record, index) => <tr key={record.correlation_id ?? index}><td className="whitespace-nowrap p-3">{formatTime(record.at)}</td><td className="p-3"><Badge tone={record.outcome === "ok" ? "success" : record.outcome === "limit" ? "warning" : "danger"}>{record.outcome ?? "unknown"}</Badge></td><td className="p-3 font-mono">{record.rounds ?? 0}</td><td className="p-3 font-mono">{formatDuration(record.duration_seconds)}</td><td className="p-3"><span className="line-clamp-2">{record.tool_operations?.join(", ") || "None"}</span></td></tr>)}</tbody></table></div> : <EmptyState icon={Clock3} text="No assistant turns have been recorded." />}</div>;
}

function AuditView({ audit }: { audit: AgentAudit | null }) {
  if (!audit?.records.length) return <EmptyState icon={ShieldCheck} text="No LimeOps audit events have been recorded." />;
  return <div className="space-y-4"><div><h3 className="font-mono text-sm font-semibold">LimeOps audit</h3><p className="text-xs text-muted-foreground">Recent broker decisions and read-only tool execution results.</p></div><div className="overflow-x-auto rounded-md border border-border"><table className="w-full min-w-[720px] text-left text-xs"><thead className="border-b border-border bg-muted/30 font-mono text-dim"><tr><th className="p-3 font-medium">Time</th><th className="p-3 font-medium">Actor</th><th className="p-3 font-medium">Operation</th><th className="p-3 font-medium">Phase</th><th className="p-3 font-medium">Result</th><th className="p-3 font-medium">Duration</th></tr></thead><tbody className="divide-y divide-border">{audit.records.map((record, index) => <tr key={record.audit_id ?? `${record.request_id}-${index}`}><td className="whitespace-nowrap p-3">{formatTime(record.ts)}</td><td className="p-3">{record.actor_username ?? record.actor_id ?? record.actor_type ?? "system"}</td><td className="p-3 font-mono">{record.operation ?? "-"}</td><td className="p-3">{record.phase ?? "-"}</td><td className="p-3"><Badge tone={record.ok ? "success" : "danger"}>{record.ok ? "Allowed" : record.error_code ?? "Denied"}</Badge></td><td className="p-3 font-mono">{record.duration_ms === undefined ? "-" : `${record.duration_ms} ms`}</td></tr>)}</tbody></table></div></div>;
}

function EmptyState({ icon: Icon, text }: { icon: typeof Activity; text: string }) {
  return <div className="flex min-h-36 flex-col items-center justify-center gap-2 text-center text-muted-foreground"><Icon className="h-5 w-5" /><p className="text-sm">{text}</p></div>;
}
