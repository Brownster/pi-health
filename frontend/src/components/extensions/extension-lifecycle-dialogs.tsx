import { useId, useState } from "react";
import { AlertTriangle, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import type { ExtensionDescriptor, ExtensionLifecycleAction } from "@/lib/capabilities";
import { cn } from "@/lib/utils";

export type ExtensionDialogAction = ExtensionLifecycleAction | "remove";

const ACTION_COPY: Record<ExtensionDialogAction, { title: string; message: string; confirm: string }> = {
  enable: {
    title: "Enable extension",
    message: "The provider becomes available after LimeOS restarts.",
    confirm: "Enable",
  },
  disable: {
    title: "Disable extension",
    message: "Provider configuration is preserved, but its capabilities stop loading after restart.",
    confirm: "Disable",
  },
  update: {
    title: "Update extension",
    message: "The managed GitHub checkout will move to the latest fetched revision. Configuration is preserved.",
    confirm: "Update",
  },
  repair: {
    title: "Repair extension",
    message: "The managed checkout will be restored from its configured source. Configuration is preserved.",
    confirm: "Repair",
  },
  remove: {
    title: "Remove extension",
    message: "The managed package files and installation record will be removed. Disable it first.",
    confirm: "Remove",
  },
};

function DialogFrame({
  children,
  description,
  onClose,
  title,
}: {
  children: React.ReactNode;
  description: string;
  onClose: () => void;
  title: string;
}) {
  const titleId = useId();
  return (
    <ModalOverlay onClose={onClose}>
      <div aria-labelledby={titleId} aria-modal="true" className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-card" role="dialog">
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 className="font-mono text-base font-semibold" id={titleId}>{title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
          <Button aria-label="Close dialog" className="h-11 w-11 shrink-0 px-0" onClick={onClose} variant="ghost"><X aria-hidden="true" className="h-4 w-4" /></Button>
        </header>
        {children}
      </div>
    </ModalOverlay>
  );
}

export function ExtensionLifecycleDialog({
  action,
  extension,
  onClose,
  onConfirm,
  pending,
}: {
  action: ExtensionDialogAction;
  extension: ExtensionDescriptor;
  onClose: () => void;
  onConfirm: () => void;
  pending: boolean;
}) {
  const copy = ACTION_COPY[action];
  const [confirmation, setConfirmation] = useState("");
  const destructive = action === "remove";
  const canConfirm = !pending && (!destructive || confirmation === extension.id);

  return (
    <DialogFrame description={extension.name} onClose={onClose} title={copy.title}>
      <div className="space-y-4 px-4 py-5 sm:px-5">
        <div className={cn("flex items-start gap-2 border-l-2 px-3 py-2.5 text-sm", destructive ? "border-danger bg-danger/5 text-danger" : "border-warning bg-warning/5 text-warning")}>
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{copy.message}</p>
        </div>
        {destructive ? (
          <label className="block space-y-1.5">
            <span className="text-sm text-foreground">Type <code className="text-danger">{extension.id}</code> to confirm</span>
            <input autoComplete="off" className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-extension-remove-confirmation onChange={(event) => setConfirmation(event.target.value)} spellCheck={false} value={confirmation} />
          </label>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
          <Button disabled={pending} onClick={onClose} variant="outline">Cancel</Button>
          <Button className={destructive ? "border-danger/30 bg-danger/10 text-danger hover:bg-danger/15" : undefined} data-extension-confirm={action} disabled={!canConfirm} onClick={onConfirm} variant="outline">
            {pending ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : null}
            {pending ? `${copy.confirm}...` : copy.confirm}
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}

export function ExtensionInstallDialog({
  onClose,
  onConfirm,
  pending,
}: {
  onClose: () => void;
  onConfirm: (values: { type: "github"; source: string; id?: string }) => void;
  pending: boolean;
}) {
  const [source, setSource] = useState("");
  const [extensionId, setExtensionId] = useState("");
  const valid = source.trim().length > 0 && !pending;

  return (
    <DialogFrame description="Install a reviewed capability provider from GitHub." onClose={onClose} title="Install extension">
      <div className="space-y-4 px-4 py-5 sm:px-5">
        <div className="flex items-start gap-2 border-l-2 border-warning bg-warning/5 px-3 py-2.5 text-sm text-warning">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          <p>Extensions run with LimeOS provider permissions. Install only a source you trust and have reviewed.</p>
        </div>
        <label className="block space-y-1.5">
          <span className="text-sm text-foreground">GitHub repository</span>
          <input autoComplete="url" className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-extension-install-source onChange={(event) => setSource(event.target.value)} placeholder="owner/repository" spellCheck={false} value={source} />
        </label>
        <label className="block space-y-1.5">
          <span className="text-sm text-foreground">Extension ID <span className="text-dim">optional</span></span>
          <input autoComplete="off" className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-extension-install-id onChange={(event) => setExtensionId(event.target.value)} placeholder="derived from repository" spellCheck={false} value={extensionId} />
        </label>
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
          <Button disabled={pending} onClick={onClose} variant="outline">Cancel</Button>
          <Button data-extension-install-confirm disabled={!valid} onClick={() => onConfirm({ type: "github", source: source.trim(), ...(extensionId.trim() ? { id: extensionId.trim() } : {}) })}>
            {pending ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : null}
            {pending ? "Installing..." : "Install"}
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}
