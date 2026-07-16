import { useEffect, useState } from "react";
import { ArrowRight, ClipboardList, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { getPendingSetupActions, type SetupAction } from "@/lib/setup";

const DISMISS_KEY = "pihealth-setup-dismissed";

function readDismissed(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(DISMISS_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function persistDismissed(ids: Iterable<string>): void {
  try {
    window.sessionStorage.setItem(DISMISS_KEY, JSON.stringify([...ids]));
  } catch {
    // sessionStorage unavailable — the modal simply reappears on next load.
  }
}

/**
 * After an update, an integration may need a one-time action the app cannot perform on its
 * own (e.g. creating a Mattermost channel, which needs an admin session we do not store).
 * This surfaces those tasks in a modal that explains what to do. Dismissal is per-session,
 * so a still-outstanding task reappears on the next login until it is actually completed.
 */
export function SetupTasksModal() {
  const { state } = useAuth();
  const navigate = useNavigate();
  const [actions, setActions] = useState<SetupAction[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(() => readDismissed());

  useEffect(() => {
    if (state !== "authenticated") return undefined;
    const controller = new AbortController();
    getPendingSetupActions(controller.signal)
      .then((result) => setActions(result.actions ?? []))
      .catch(() => {
        /* non-blocking: never let a setup check break the app */
      });
    return () => controller.abort();
  }, [state]);

  const pending = actions.filter((action) => !dismissed.has(action.id));
  if (state !== "authenticated" || pending.length === 0) {
    return null;
  }

  function dismissAll() {
    const next = new Set(dismissed);
    pending.forEach((action) => next.add(action.id));
    setDismissed(next);
    persistDismissed(next);
  }

  function act(action: SetupAction) {
    dismissAll();
    navigate(action.href);
  }

  return (
    <ModalOverlay onClose={dismissAll}>
      <Card aria-labelledby="setup-tasks-title" aria-modal="true" className="w-full max-w-lg" role="dialog">
        <CardHeader className="flex flex-row items-start justify-between border-b border-border">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary">
              <ClipboardList className="h-5 w-5" />
            </span>
            <div>
              <CardTitle id="setup-tasks-title">Action needed after update</CardTitle>
              <CardDescription>
                {pending.length === 1 ? "One item needs your attention." : `${pending.length} items need your attention.`}
              </CardDescription>
            </div>
          </div>
          <Button aria-label="Dismiss" className="w-11 px-0" onClick={dismissAll} variant="ghost">
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4 p-4 sm:p-6">
          <ul className="space-y-4">
            {pending.map((action) => (
              <li className="rounded-md border border-border p-4" key={action.id}>
                <p className="text-sm font-semibold">{action.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{action.body}</p>
                <Button className="mt-3 gap-2" data-setup-action={action.id} onClick={() => act(action)} size="sm">
                  {action.action_label}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
          <div className="flex justify-end">
            <Button onClick={dismissAll} variant="ghost">Remind me later</Button>
          </div>
        </CardContent>
      </Card>
    </ModalOverlay>
  );
}
