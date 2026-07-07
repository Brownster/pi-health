import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import type { CreateStackInput } from "@/lib/stacks";

const STACK_NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;
const DEFAULT_COMPOSE = `services:
  app:
    image: nginx:latest
    restart: unless-stopped
`;

export function StackCreateModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (input: CreateStackInput) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [composeContent, setComposeContent] = useState(DEFAULT_COMPOSE);
  const [envContent, setEnvContent] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const normalizedName = name.trim();
    if (!STACK_NAME_PATTERN.test(normalizedName)) {
      setError(
        "Use letters, numbers, dots, underscores, or hyphens; start with a letter or number.",
      );
      return;
    }
    setPending(true);
    setError(null);
    try {
      await onCreate({ name: normalizedName, composeContent, envContent });
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Unable to create stack",
      );
      setPending(false);
    }
  };

  return (
    <ModalOverlay onClose={pending ? () => undefined : onClose}>
      <Card
        aria-labelledby="v2-stack-create-title"
        aria-modal="true"
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden"
        id="v2-stack-create-modal"
        role="dialog"
      >
        <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
          <div className="space-y-1">
            <CardTitle id="v2-stack-create-title">New stack</CardTitle>
            <CardDescription>
              Create a Compose project with an optional environment file.
            </CardDescription>
          </div>
          <Button disabled={pending} onClick={onClose} variant="outline">
            Close
          </Button>
        </CardHeader>
        <CardContent className="space-y-4 overflow-auto p-4 sm:p-5">
          <label className="block space-y-1.5 text-sm font-medium">
            Stack name
            <input
              autoComplete="off"
              autoFocus
              className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
              id="v2-stack-create-name"
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              placeholder="media-stack"
              value={name}
            />
          </label>
          <label className="block space-y-1.5 text-sm font-medium">
            Compose file
            <textarea
              className="h-56 w-full resize-y rounded-md border border-border bg-background p-3 font-mono text-xs sm:text-sm"
              id="v2-stack-create-compose"
              onChange={(event) => setComposeContent(event.target.value)}
              spellCheck={false}
              value={composeContent}
            />
          </label>
          <label className="block space-y-1.5 text-sm font-medium">
            Environment file <span className="text-muted-foreground">(optional)</span>
            <textarea
              className="h-28 w-full resize-y rounded-md border border-border bg-background p-3 font-mono text-xs sm:text-sm"
              id="v2-stack-create-env"
              onChange={(event) => setEnvContent(event.target.value)}
              placeholder="TZ=Europe/London"
              spellCheck={false}
              value={envContent}
            />
          </label>
          {error ? (
            <p aria-live="assertive" className="text-sm text-danger" role="alert">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            <Button disabled={pending} onClick={onClose} variant="outline">
              Cancel
            </Button>
            <Button
              className="gap-2"
              disabled={pending}
              id="v2-stack-create-submit"
              onClick={() => void submit()}
            >
              {pending ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : null}
              {pending ? "Creating..." : "Create stack"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </ModalOverlay>
  );
}
