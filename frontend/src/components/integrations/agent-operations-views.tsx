import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Ban,
  CalendarClock,
  Check,
  ChevronRight,
  CircleStop,
  FileWarning,
  History,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  actionCanBeApproved,
  actionCanBeCancelled,
  actionCanBeRejected,
  approveAgentAction,
  cancelAgentAction,
  createAgentSchedule,
  editableSchedule,
  editableFinding,
  getAgentAction,
  getAgentActionCapabilities,
  getAgentActions,
  getAgentAutomationPolicy,
  getAgentSchedules,
  getAgentFinding,
  getAgentFindings,
  rejectAgentAction,
  rejectAgentFinding,
  newAgentSchedule,
  scheduleReady,
  updateAgentSchedule,
  updateAgentAutomationPolicy,
  updateAgentFinding,
  type AgentAction,
  type AgentActionCapability,
  type AgentActionState,
  type AgentAuthorityMode,
  type AgentAutomationPolicy,
  type AgentDiagnosticCheck,
  type AgentFinding,
  type AgentFindingContent,
  type AgentSchedule,
  type AgentScheduleInput,
  type AgentScheduleUpdate,
  type AgentTargetPolicy,
} from "@/lib/agent-operations";

const FIELD_CLASS =
  "min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const AUTHORITY_OPTIONS: AgentAuthorityMode[] = ["observe", "propose", "approval"];
const TRIGGERS = ["interactive", "scheduled", "event"] as const;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed";
}

function formatTime(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function humanize(value: string): string {
  return value.replace(/[._]/g, " ");
}

function actionTone(state: AgentActionState): BadgeProps["tone"] {
  if (state === "succeeded") return "success";
  if (["awaiting_approval", "proposed", "authorised"].includes(state)) return "warning";
  if (["executing", "verifying", "rolling_back"].includes(state)) return "info";
  if (["execution_failed", "verification_failed", "rollback_failed", "escalation_required", "precondition_changed"].includes(state)) return "danger";
  return "neutral";
}

function LoadingState({ label }: { label: string }) {
  return <div className="flex min-h-36 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />{label}</div>;
}

function InlineError({ message }: { message: string }) {
  return <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-sm text-danger" role="alert"><TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />{message}</div>;
}

export function AgentActionsView({ canAdmin }: { canAdmin: boolean }) {
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [selected, setSelected] = useState<AgentAction | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await getAgentActions(100, signal);
      setActions(result.actions);
      setError(null);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function selectAction(action: AgentAction) {
    setBusy(action.id);
    try {
      setSelected(await getAgentAction(action.id));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function mutate(action: "approve" | "reject" | "cancel") {
    if (!selected) return;
    setBusy(action);
    try {
      const updated = action === "approve"
        ? await approveAgentAction(selected.id)
        : action === "reject"
          ? await rejectAgentAction(selected.id)
          : await cancelAgentAction(selected.id);
      const detail = await getAgentAction(updated.id);
      setSelected(detail);
      setActions((current) => current.map((item) => item.id === detail.id ? detail : item));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !actions.length) return <LoadingState label="Loading action queue" />;

  return (
    <div className="space-y-4" data-agent-actions-view>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div><h3 className="font-mono text-sm font-semibold">Action review</h3><p className="text-xs text-muted-foreground">Inspect the exact target, impact, evidence, and execution history before granting authority.</p></div>
        <Button className="gap-2 self-start" disabled={loading} onClick={() => void load()} size="sm" variant="outline"><RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />Refresh</Button>
      </div>
      {error ? <InlineError message={error} /> : null}
      {!actions.length ? <div className="flex min-h-36 flex-col items-center justify-center gap-2 text-center text-muted-foreground"><History className="h-5 w-5" /><p className="text-sm">No agent actions have been proposed.</p></div> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(24rem,1.2fr)]">
          <div className="max-h-[34rem] divide-y divide-border overflow-auto rounded-md border border-border" aria-label="Agent action queue">
            {actions.map((action) => (
              <button className="flex min-h-20 w-full cursor-pointer items-start justify-between gap-3 p-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring" key={action.id} onClick={() => void selectAction(action)} type="button">
                <span className="min-w-0"><span className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-medium">{humanize(action.operation)}</span><Badge tone={actionTone(action.state)}>{humanize(action.state)}</Badge><Badge>{action.risk}</Badge></span><span className="mt-1 block truncate text-sm">{action.target}</span><span className="mt-1 block text-xs text-dim">{formatTime(action.created_at)}</span></span>
                {busy === action.id ? <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin" /> : <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-dim" />}
              </button>
            ))}
          </div>
          {selected ? <ActionDetail action={selected} busy={busy !== null} canAdmin={canAdmin} onApprove={() => void mutate("approve")} onCancel={() => void mutate("cancel")} onClose={() => setSelected(null)} onReject={() => void mutate("reject")} /> : <div className="flex min-h-52 items-center justify-center rounded-md border border-dashed border-border px-6 text-center text-sm text-muted-foreground">Select an action to review its immutable proposal and event history.</div>}
        </div>
      )}
    </div>
  );
}

function ActionDetail({ action, busy, canAdmin, onApprove, onCancel, onClose, onReject }: { action: AgentAction; busy: boolean; canAdmin: boolean; onApprove: () => void; onCancel: () => void; onClose: () => void; onReject: () => void }) {
  return (
    <section className="space-y-4 rounded-md border border-border bg-muted/10 p-4" aria-label={`Action ${action.id}`}>
      <div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap gap-2"><Badge tone={actionTone(action.state)}>{humanize(action.state)}</Badge><Badge>{action.risk}</Badge><Badge tone="info">{humanize(action.authority_mode)}</Badge></div><h4 className="mt-2 font-mono text-sm font-semibold">{action.operation}</h4><p className="text-xs text-muted-foreground">{action.target} · expires {formatTime(action.expires_at)}</p></div><Button aria-label="Close action detail" onClick={onClose} size="icon" variant="ghost"><X className="h-4 w-4" /></Button></div>
      <div className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2"><Detail label="Reason" value={action.reason} /><Detail label="Expected impact" value={action.impact} /><Detail label="Requested by" value={action.actor.username ?? `${action.actor.type}:${action.actor.id}`} /><Detail label="Trigger" value={action.trigger} /></div>
      <div><p className="mb-2 font-mono text-[10px] uppercase text-dim">Evidence</p><div className="flex flex-wrap gap-2">{action.evidence_ids.length ? action.evidence_ids.map((id) => <Badge key={id}>{id}</Badge>) : <span className="text-xs text-muted-foreground">No evidence references attached</span>}</div></div>
      <details className="rounded-md border border-border"><summary className="min-h-11 cursor-pointer px-3 py-3 font-mono text-xs">Verified parameters</summary><pre className="overflow-auto border-t border-border bg-background/60 p-3 text-xs text-muted-foreground">{JSON.stringify(action.params, null, 2)}</pre></details>
      {action.events?.length ? <div><p className="mb-2 font-mono text-[10px] uppercase text-dim">Event history</p><ol className="space-y-2 border-l border-border pl-3">{action.events.map((event, index) => <li className="text-xs" key={`${event.created_at}-${index}`}><span className="font-medium">{humanize(event.phase)}</span><span className="ml-2 text-dim">{formatTime(event.created_at)}</span></li>)}</ol></div> : null}
      {canAdmin && (actionCanBeApproved(action) || actionCanBeRejected(action) || actionCanBeCancelled(action)) ? <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">{actionCanBeCancelled(action) ? <Button className="gap-2" disabled={busy} onClick={onCancel} size="sm" variant="outline"><CircleStop className="h-3.5 w-3.5" />Cancel</Button> : null}{actionCanBeRejected(action) ? <Button className="gap-2" disabled={busy} onClick={onReject} size="sm" variant="danger"><Ban className="h-3.5 w-3.5" />Reject</Button> : null}{actionCanBeApproved(action) ? <Button className="gap-2" disabled={busy} onClick={onApprove} size="sm" variant="success">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}Approve once</Button> : null}</div> : null}
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="bg-card p-3"><p className="font-mono text-[10px] uppercase text-dim">{label}</p><p className="mt-1 whitespace-pre-wrap text-sm">{value}</p></div>;
}

export function AgentFindingsView({ canAdmin }: { canAdmin: boolean }) {
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [selected, setSelected] = useState<AgentFinding | null>(null);
  const [editing, setEditing] = useState<AgentFindingContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      setFindings((await getAgentFindings(100, signal)).findings);
      setError(null);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  async function selectFinding(finding: AgentFinding) {
    setBusy(true);
    try {
      const detail = await getAgentFinding(finding.id);
      setSelected(detail);
      setEditing(null);
      setError(null);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  async function save() {
    if (!selected || !editing) return;
    setBusy(true);
    try {
      const updated = await updateAgentFinding(selected.id, editing);
      setSelected(updated);
      setEditing(null);
      setFindings((current) => current.map((item) => item.id === updated.id ? updated : item));
      setError(null);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  async function reject() {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await rejectAgentFinding(selected.id);
      setSelected(updated);
      setEditing(null);
      setFindings((current) => current.map((item) => item.id === updated.id ? updated : item));
      setError(null);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }

  if (loading && !findings.length) return <LoadingState label="Loading private findings" />;

  return <div className="space-y-4" data-agent-findings-view><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><h3 className="font-mono text-sm font-semibold">Private findings</h3><p className="text-xs text-muted-foreground">Review redacted bug, feature, maintenance, and documentation drafts. Nothing is published from this screen.</p></div><Button className="gap-2 self-start" disabled={loading} onClick={() => void load()} size="sm" variant="outline"><RefreshCw className="h-3.5 w-3.5" />Refresh</Button></div>{error ? <InlineError message={error} /> : null}{!findings.length ? <div className="flex min-h-36 flex-col items-center justify-center gap-2 text-center text-muted-foreground"><FileWarning className="h-5 w-5" /><p className="text-sm">No findings are waiting for review.</p></div> : <div className="grid gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(24rem,1.2fr)]"><div className="max-h-[38rem] divide-y divide-border overflow-auto rounded-md border border-border">{findings.map((finding) => <button className="flex min-h-20 w-full cursor-pointer items-start justify-between gap-3 p-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring" key={finding.id} onClick={() => void selectFinding(finding)} type="button"><span className="min-w-0"><span className="flex flex-wrap gap-2"><Badge tone={finding.kind === "bug" ? "danger" : "info"}>{humanize(finding.kind)}</Badge><Badge tone={finding.state === "draft" ? "warning" : "neutral"}>{finding.state}</Badge>{finding.redaction_applied ? <Badge tone="success">redacted</Badge> : null}</span><span className="mt-2 block truncate text-sm font-medium">{finding.title}</span><span className="mt-1 block text-xs text-dim">{finding.component} · {formatTime(finding.updated_at)}</span></span><ChevronRight className="mt-1 h-4 w-4 shrink-0 text-dim" /></button>)}</div>{selected ? editing ? <FindingEditor busy={busy} finding={editing} onCancel={() => setEditing(null)} onChange={setEditing} onSave={() => void save()} /> : <FindingDetail busy={busy} canAdmin={canAdmin} finding={selected} onClose={() => setSelected(null)} onEdit={() => setEditing(editableFinding(selected))} onReject={() => void reject()} /> : <div className="flex min-h-52 items-center justify-center rounded-md border border-dashed border-border px-6 text-center text-sm text-muted-foreground">Select a finding to review its draft and evidence references.</div>}</div>}</div>;
}

function FindingDetail({ busy, canAdmin, finding, onClose, onEdit, onReject }: { busy: boolean; canAdmin: boolean; finding: AgentFinding; onClose: () => void; onEdit: () => void; onReject: () => void }) {
  return <section className="space-y-4 rounded-md border border-border bg-muted/10 p-4"><div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap gap-2"><Badge tone={finding.kind === "bug" ? "danger" : "info"}>{humanize(finding.kind)}</Badge><Badge tone={finding.confidence === "high" ? "success" : finding.confidence === "medium" ? "warning" : "neutral"}>{finding.confidence} confidence</Badge></div><h4 className="mt-2 text-sm font-semibold">{finding.title}</h4><p className="text-xs text-muted-foreground">{finding.component} · revision {finding.revision}</p></div><Button aria-label="Close finding detail" onClick={onClose} size="icon" variant="ghost"><X className="h-4 w-4" /></Button></div><Detail label="Summary" value={finding.summary} /><Detail label="Impact" value={finding.impact} />{finding.expected_behavior ? <Detail label="Expected behavior" value={finding.expected_behavior} /> : null}{finding.actual_behavior ? <Detail label="Actual behavior" value={finding.actual_behavior} /> : null}{finding.reproduction_steps.length ? <div><p className="mb-2 font-mono text-[10px] uppercase text-dim">Reproduction steps</p><ol className="list-decimal space-y-1 pl-5 text-sm">{finding.reproduction_steps.map((step, index) => <li key={index}>{step}</li>)}</ol></div> : null}<div className="flex flex-wrap gap-2">{finding.evidence_ids.map((id) => <Badge key={id}>{id}</Badge>)}{finding.redaction_applied ? <Badge tone="success">Sensitive values redacted</Badge> : null}<Badge tone="neutral">Private draft</Badge></div>{canAdmin && finding.state === "draft" ? <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4"><Button className="gap-2" disabled={busy} onClick={onReject} size="sm" variant="danger"><Trash2 className="h-3.5 w-3.5" />Reject draft</Button><Button className="gap-2" disabled={busy} onClick={onEdit} size="sm" variant="secondary"><Pencil className="h-3.5 w-3.5" />Edit</Button></div> : null}</section>;
}

function FindingEditor({ busy, finding, onCancel, onChange, onSave }: { busy: boolean; finding: AgentFindingContent; onCancel: () => void; onChange: (value: AgentFindingContent) => void; onSave: () => void }) {
  const field = (key: keyof AgentFindingContent, value: unknown) => onChange({ ...finding, [key]: value });
  const list = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);
  const ready = finding.title.trim() && finding.summary.trim() && finding.component.trim() && finding.impact.trim();
  return <section className="space-y-4 rounded-md border border-border bg-muted/10 p-4" aria-label="Edit finding"><div><h4 className="font-mono text-sm font-semibold">Edit private draft</h4><p className="text-xs text-muted-foreground">Required fields are marked. One list item per line.</p></div><div className="grid gap-3 sm:grid-cols-2"><Field label="Title *" value={finding.title} onChange={(value) => field("title", value)} /><Field label="Component *" value={finding.component} onChange={(value) => field("component", value)} /><label className="space-y-1.5"><span className="text-xs">Kind</span><select className={FIELD_CLASS} value={finding.kind} onChange={(event) => field("kind", event.target.value)}><option value="bug">Bug</option><option value="feature_request">Feature request</option><option value="maintenance_gap">Maintenance gap</option><option value="documentation_gap">Documentation gap</option></select></label><label className="space-y-1.5"><span className="text-xs">Confidence</span><select className={FIELD_CLASS} value={finding.confidence} onChange={(event) => field("confidence", event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label></div><TextField label="Summary *" value={finding.summary} onChange={(value) => field("summary", value)} /><TextField label="Impact *" value={finding.impact} onChange={(value) => field("impact", value)} /><div className="grid gap-3 sm:grid-cols-2"><TextField label="Expected behavior" value={finding.expected_behavior} onChange={(value) => field("expected_behavior", value)} /><TextField label="Actual behavior" value={finding.actual_behavior} onChange={(value) => field("actual_behavior", value)} /><TextField label="Reproduction steps" value={finding.reproduction_steps.join("\n")} onChange={(value) => field("reproduction_steps", list(value))} /><TextField label="Acceptance criteria" value={finding.acceptance_criteria.join("\n")} onChange={(value) => field("acceptance_criteria", list(value))} /><Field label="Affected version" value={finding.affected_version} onChange={(value) => field("affected_version", value)} /><Field label="Frequency" value={finding.frequency} onChange={(value) => field("frequency", value)} /></div><TextField label="Workaround" value={finding.workaround} onChange={(value) => field("workaround", value)} /><div className="flex justify-end gap-2 border-t border-border pt-4"><Button disabled={busy} onClick={onCancel} size="sm" variant="outline">Cancel</Button><Button className="gap-2" disabled={busy || !ready} onClick={onSave} size="sm">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}Save draft</Button></div></section>;
}

function Field({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: string }) {
  return <label className="space-y-1.5"><span className="text-xs">{label}</span><input className={FIELD_CLASS} onChange={(event) => onChange(event.target.value)} value={value} /></label>;
}

function TextField({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: string }) {
  return <label className="space-y-1.5"><span className="text-xs">{label}</span><textarea className={`${FIELD_CLASS} min-h-24 resize-y`} onChange={(event) => onChange(event.target.value)} value={value} /></label>;
}

function AuthorityPolicyView() {
  const [policy, setPolicy] = useState<AgentAutomationPolicy | null>(null);
  const [capabilities, setCapabilities] = useState<AgentActionCapability[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newTargets, setNewTargets] = useState<Record<string, string>>({});

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const [nextPolicy, catalogue] = await Promise.all([getAgentAutomationPolicy(signal), getAgentActionCapabilities(signal)]);
      setPolicy(nextPolicy);
      setCapabilities(catalogue.capabilities);
      setError(null);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(errorMessage(caught));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  const capabilityByOperation = useMemo(() => new Map(capabilities.map((item) => [item.operation, item])), [capabilities]);
  function operationChange(operation: string, value: Partial<AgentAutomationPolicy["operations"][string]>) {
    if (!policy) return;
    setSaved(false);
    setPolicy({ ...policy, operations: { ...policy.operations, [operation]: { ...policy.operations[operation], ...value } } });
  }
  function targetChange(operation: string, target: string, value: AgentTargetPolicy | null) {
    if (!policy) return;
    const current = policy.operations[operation];
    const targets = { ...current.targets };
    if (value) targets[target] = value; else delete targets[target];
    operationChange(operation, { targets });
  }
  function addTarget(operation: string) {
    const target = (newTargets[operation] ?? "").trim();
    if (!target || policy?.operations[operation].targets[target]) return;
    targetChange(operation, target, { interactive: "approval", scheduled: "observe", event: "observe" });
    setNewTargets((current) => ({ ...current, [operation]: "" }));
  }
  async function save() {
    if (!policy) return;
    setSaving(true);
    try { setPolicy(await updateAgentAutomationPolicy(policy)); setSaved(true); setError(null); } catch (caught) { setError(errorMessage(caught)); } finally { setSaving(false); }
  }

  if (loading && !policy) return <LoadingState label="Loading automation policy" />;
  if (!policy) return <div className="space-y-3">{error ? <InlineError message={error} /> : null}</div>;
  const ttlValid = Number.isInteger(policy.defaults.proposal_ttl_seconds)
    && policy.defaults.proposal_ttl_seconds >= 60
    && policy.defaults.proposal_ttl_seconds <= 86400;
  return <div className="space-y-5" data-agent-automation-view><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><h3 className="font-mono text-sm font-semibold">Authority policy</h3><p className="text-xs text-muted-foreground">Targets are deny-by-default. Automatic supervised and autonomous modes remain locked until the repair canary gate passes.</p></div><Button className="gap-2 self-start" disabled={loading} onClick={() => void load()} size="sm" variant="outline"><RefreshCw className="h-3.5 w-3.5" />Reload</Button></div>{error ? <InlineError message={error} /> : null}<label className={`flex items-start gap-3 border-l-2 px-4 py-3 ${policy.kill_switch ? "border-success bg-success/5" : "border-danger bg-danger/5"}`}><input checked={policy.kill_switch} className="mt-0.5 h-5 w-5 accent-primary" onChange={(event) => { setSaved(false); setPolicy({ ...policy, kill_switch: event.target.checked }); }} type="checkbox" /><span><span className="flex items-center gap-2 text-sm font-medium"><ShieldAlert className="h-4 w-4" />Emergency stop {policy.kill_switch ? "engaged" : "released"}</span><span className="mt-1 block text-xs text-muted-foreground">When engaged, approvals and execution fail closed. Policy review and private findings remain available.</span></span></label><label className="block max-w-xs space-y-1.5"><span className="text-xs">Proposal expiry (seconds)</span><input className={FIELD_CLASS} max={86400} min={60} onChange={(event) => { setSaved(false); setPolicy({ ...policy, defaults: { proposal_ttl_seconds: Number(event.target.value) } }); }} type="number" value={policy.defaults.proposal_ttl_seconds} /></label><div className="space-y-4">{Object.entries(policy.operations).map(([operation, config]) => { const capability = capabilityByOperation.get(operation); return <section className="rounded-md border border-border" key={operation}><div className="flex flex-col gap-3 border-b border-border bg-muted/20 p-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h4 className="font-mono text-xs font-semibold">{operation}</h4><Badge>{capability?.risk ?? "unknown risk"}</Badge></div><p className="mt-1 text-xs text-muted-foreground">{Object.keys(config.targets).length} allowlisted target{Object.keys(config.targets).length === 1 ? "" : "s"}</p></div><label className="flex min-h-11 items-center gap-2 text-sm"><input checked={config.enabled} className="h-5 w-5 accent-primary" onChange={(event) => operationChange(operation, { enabled: event.target.checked })} type="checkbox" />Capability enabled</label></div><div className="space-y-3 p-3"><Field label="Approvers (comma separated actor IDs)" value={config.approvers.join(", ")} onChange={(value) => operationChange(operation, { approvers: value.split(",").map((item) => item.trim()).filter(Boolean) })} />{Object.entries(config.targets).map(([target, modes]) => <div className="grid gap-2 rounded-md border border-border p-3 lg:grid-cols-[minmax(10rem,1fr)_repeat(3,minmax(8rem,0.7fr))_auto] lg:items-end" key={target}><div><p className="font-mono text-[10px] uppercase text-dim">Target</p><p className="mt-2 truncate text-sm" title={target}>{target}</p></div>{TRIGGERS.map((trigger) => <label className="space-y-1" key={trigger}><span className="font-mono text-[10px] uppercase text-dim">{trigger}</span><select className={FIELD_CLASS} onChange={(event) => targetChange(operation, target, { ...modes, [trigger]: event.target.value as AgentAuthorityMode })} value={modes[trigger]}>{AUTHORITY_OPTIONS.filter((mode) => mode === "observe" || capability?.eligible_modes.includes(mode)).map((mode) => <option key={mode} value={mode}>{humanize(mode)}</option>)}</select></label>)}<Button aria-label={`Remove ${target} target`} onClick={() => targetChange(operation, target, null)} size="icon" variant="ghost"><Trash2 className="h-4 w-4" /></Button></div>)}<div className="flex flex-col gap-2 sm:flex-row"><input className={FIELD_CLASS} onChange={(event) => setNewTargets((current) => ({ ...current, [operation]: event.target.value }))} placeholder="Exact target name" value={newTargets[operation] ?? ""} /><Button className="gap-2 shrink-0" disabled={!newTargets[operation]?.trim()} onClick={() => addTarget(operation)} variant="secondary"><Plus className="h-4 w-4" />Allow target</Button></div></div></section>; })}</div><div className="flex flex-col-reverse gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-end">{saved ? <span className="flex items-center gap-2 text-sm text-success" role="status"><Check className="h-4 w-4" />Policy saved</span> : null}<Button className="gap-2" disabled={saving || !ttlValid} onClick={() => void save()}>{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}Save policy</Button></div></div>;
}

type ScheduleDraft =
  | { id: null; value: AgentScheduleInput }
  | { id: string; value: AgentScheduleUpdate };

function occurrenceTone(state?: string): BadgeProps["tone"] {
  if (state === "delivered") return "success";
  if (["running", "report_ready", "delivering"].includes(state ?? "")) return "info";
  if (state) return "warning";
  return "neutral";
}

function ScheduledReportsView() {
  const [schedules, setSchedules] = useState<AgentSchedule[]>([]);
  const [catalogue, setCatalogue] = useState<AgentDiagnosticCheck[]>([]);
  const [editor, setEditor] = useState<ScheduleDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await getAgentSchedules(signal);
      setSchedules(result.schedules);
      setCatalogue(result.diagnostic_catalogue);
      setError(null);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(errorMessage(caught));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function saveSchedule() {
    if (!editor || !scheduleReady(editor.value)) return;
    setBusy(editor.id ?? "new");
    try {
      const savedSchedule = editor.id
        ? await updateAgentSchedule(editor.id, editor.value as AgentScheduleUpdate)
        : await createAgentSchedule(editor.value);
      setSchedules((current) => [
        savedSchedule,
        ...current.filter((item) => item.id !== savedSchedule.id),
      ]);
      setEditor(null);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function toggleSchedule(schedule: AgentSchedule) {
    setBusy(schedule.id);
    try {
      const updated = await updateAgentSchedule(schedule.id, {
        ...editableSchedule(schedule),
        enabled: !schedule.enabled,
      });
      setSchedules((current) => current.map((item) => (
        item.id === updated.id ? updated : item
      )));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-4" data-agent-schedules-view>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <CalendarClock aria-hidden="true" className="h-4 w-4 text-primary" />
            <h3 className="font-mono text-sm font-semibold">Scheduled reports</h3>
          </div>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            Run bounded diagnostics through the read broker and deliver one report to
            Mattermost. Scheduled actions, retries, downtime, and model calls remain zero.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            className="gap-2"
            disabled={loading || busy !== null}
            onClick={() => void load()}
            size="sm"
            variant="outline"
          >
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            Refresh
          </Button>
          <Button
            className="gap-2"
            disabled={busy !== null || catalogue.length === 0}
            onClick={() => setEditor({ id: null, value: newAgentSchedule() })}
            size="sm"
          >
            <Plus className="h-3.5 w-3.5" />New report
          </Button>
        </div>
      </div>

      <div className="grid gap-3 border-l-2 border-info bg-info/5 px-4 py-3 sm:grid-cols-[auto_1fr]">
        <ShieldCheck aria-hidden="true" className="h-5 w-5 text-info" />
        <div>
          <p className="text-sm font-medium">Report-only authority boundary</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Each occurrence can perform at most 12 code-owned reads and send one report.
            It cannot propose, approve, repair, install, or change configuration.
          </p>
        </div>
      </div>

      {error ? <InlineError message={error} /> : null}
      {editor ? (
        <ScheduleEditor
          busy={busy !== null}
          catalogue={catalogue}
          draft={editor}
          onCancel={() => setEditor(null)}
          onChange={setEditor}
          onSave={() => void saveSchedule()}
        />
      ) : null}

      {loading && !schedules.length ? <LoadingState label="Loading scheduled reports" /> : null}
      {!loading && !schedules.length && !editor ? (
        <div className="flex min-h-36 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border px-6 text-center text-muted-foreground">
          <CalendarClock className="h-5 w-5" />
          <p className="text-sm">No report schedules have been created.</p>
          <p className="text-xs">Start with a disabled schedule if you want to review it before its first run.</p>
        </div>
      ) : null}
      {schedules.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {schedules.map((schedule) => (
            <article className="rounded-md border border-border bg-muted/10 p-4" key={schedule.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="truncate text-sm font-semibold">{schedule.name}</h4>
                    <Badge tone={schedule.enabled ? "success" : "neutral"}>
                      {schedule.enabled ? "enabled" : "disabled"}
                    </Badge>
                    <Badge tone="info">report only</Badge>
                  </div>
                  <p className="mt-2 font-mono text-xs text-muted-foreground">
                    {schedule.window.cron} · {schedule.window.timezone}
                  </p>
                </div>
                <Button
                  aria-label={`Edit ${schedule.name}`}
                  disabled={busy !== null}
                  onClick={() => setEditor({ id: schedule.id, value: editableSchedule(schedule) })}
                  size="icon"
                  variant="ghost"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              </div>
              <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
                <div><dt className="font-mono text-[10px] uppercase text-dim">Next run</dt><dd className="mt-1">{formatTime(schedule.next_run)}</dd></div>
                <div><dt className="font-mono text-[10px] uppercase text-dim">Checks</dt><dd className="mt-1">{schedule.checks.length} of 12 maximum</dd></div>
                <div><dt className="font-mono text-[10px] uppercase text-dim">Last occurrence</dt><dd className="mt-1"><Badge tone={occurrenceTone(schedule.last_occurrence?.state)}>{humanize(schedule.last_occurrence?.state ?? "not run")}</Badge></dd></div>
                <div><dt className="font-mono text-[10px] uppercase text-dim">Delivery</dt><dd className="mt-1">Mattermost alerts · immediate</dd></div>
              </dl>
              <div className="mt-4 flex justify-end border-t border-border pt-3">
                <Button
                  disabled={busy !== null}
                  onClick={() => void toggleSchedule(schedule)}
                  size="sm"
                  variant={schedule.enabled ? "warning" : "success"}
                >
                  {busy === schedule.id ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : null}
                  {schedule.enabled ? "Disable schedule" : "Enable schedule"}
                </Button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ScheduleEditor({
  busy,
  catalogue,
  draft,
  onCancel,
  onChange,
  onSave,
}: {
  busy: boolean;
  catalogue: AgentDiagnosticCheck[];
  draft: ScheduleDraft;
  onCancel: () => void;
  onChange: (draft: ScheduleDraft) => void;
  onSave: () => void;
}) {
  const value = draft.value;
  const catalogueByOperation = new Map(catalogue.map((item) => [item.operation, item]));
  const change = (next: AgentScheduleInput | AgentScheduleUpdate) => {
    onChange({ ...draft, value: next } as ScheduleDraft);
  };
  const setChecks = (checks: AgentScheduleInput["checks"]) => {
    change({ ...value, checks, budgets: { ...value.budgets, max_checks: checks.length } });
  };
  const updateCheck = (index: number, operation: string, parameterValue = "") => {
    const definition = catalogueByOperation.get(operation);
    const checks = value.checks.map((check, checkIndex) => checkIndex === index
      ? { operation, params: definition?.parameter ? { [definition.parameter]: parameterValue } : {} }
      : check);
    setChecks(checks);
  };

  return (
    <section className="space-y-4 rounded-md border border-primary/30 bg-primary/5 p-4" aria-label={draft.id ? "Edit report schedule" : "Create report schedule"}>
      <div>
        <h4 className="font-mono text-sm font-semibold">{draft.id ? "Edit report schedule" : "Create report schedule"}</h4>
        <p className="mt-1 text-xs text-muted-foreground">Five-field cron expressions use the selected IANA timezone. All write budgets are fixed at zero.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Schedule name *" value={value.name} onChange={(name) => change({ ...value, name })} />
        <label className="flex min-h-11 items-center gap-3 self-end rounded-md border border-border px-3 text-sm">
          <input checked={value.enabled} className="h-5 w-5 accent-primary" onChange={(event) => change({ ...value, enabled: event.target.checked })} type="checkbox" />
          Enable after saving
        </label>
        <Field label="Cron expression *" value={value.window.cron} onChange={(cron) => change({ ...value, window: { ...value.window, cron } })} />
        <Field label="IANA timezone *" value={value.window.timezone} onChange={(timezone) => change({ ...value, window: { ...value.window, timezone } })} />
        <label className="space-y-1.5">
          <span className="text-xs">Maintenance window (minutes)</span>
          <input className={FIELD_CLASS} max={1440} min={1} onChange={(event) => change({ ...value, window: { ...value.window, duration_minutes: Number(event.target.value) } })} type="number" value={value.window.duration_minutes} />
        </label>
        <div className="rounded-md border border-border bg-background/60 px-3 py-2 text-xs">
          <p className="font-mono text-[10px] uppercase text-dim">Fixed budgets</p>
          <p className="mt-1">{value.checks.length} checks · 1 report · 0 actions · 0 retries · 0 model calls</p>
        </div>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div><p className="text-sm font-medium">Diagnostic checks</p><p className="text-xs text-muted-foreground">Checks run in order; one failure still produces a partial report.</p></div>
          <Button
            className="gap-2"
            disabled={value.checks.length >= 12 || catalogue.length === 0}
            onClick={() => {
              const next = catalogue[0];
              setChecks([...value.checks, { operation: next.operation, params: next.parameter ? { [next.parameter]: "" } : {} }]);
            }}
            size="sm"
            variant="secondary"
          >
            <Plus className="h-3.5 w-3.5" />Add check
          </Button>
        </div>
        {value.checks.map((check, index) => {
          const definition = catalogueByOperation.get(check.operation);
          const parameter = definition?.parameter ?? null;
          return (
            <div className="grid gap-2 rounded-md border border-border bg-background/60 p-3 sm:grid-cols-[minmax(12rem,1fr)_minmax(10rem,1fr)_auto] sm:items-end" key={`${index}-${check.operation}`}>
              <label className="space-y-1.5">
                <span className="text-xs">Operation {index + 1}</span>
                <select className={FIELD_CLASS} onChange={(event) => updateCheck(index, event.target.value)} value={check.operation}>
                  {catalogue.map((item) => <option key={item.operation} value={item.operation}>{item.operation}</option>)}
                </select>
              </label>
              {parameter ? (
                <Field label={`${humanize(parameter)} *`} value={check.params[parameter] ?? ""} onChange={(parameterValue) => updateCheck(index, check.operation, parameterValue)} />
              ) : <div className="flex min-h-11 items-center text-xs text-muted-foreground">No target parameter</div>}
              <Button aria-label={`Remove diagnostic check ${index + 1}`} disabled={value.checks.length === 1} onClick={() => setChecks(value.checks.filter((_, checkIndex) => checkIndex !== index))} size="icon" variant="ghost"><Trash2 className="h-4 w-4" /></Button>
            </div>
          );
        })}
      </div>
      <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
        <Button disabled={busy} onClick={onCancel} size="sm" variant="outline">Cancel</Button>
        <Button className="gap-2" disabled={busy || !scheduleReady(value)} onClick={onSave} size="sm">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save schedule
        </Button>
      </div>
    </section>
  );
}

export function AgentAutomationView() {
  return (
    <div className="space-y-8" data-agent-automation-view>
      <ScheduledReportsView />
      <div className="border-t border-border pt-6">
        <AuthorityPolicyView />
      </div>
    </div>
  );
}
