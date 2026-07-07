import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { cn } from "@/lib/utils";

const TAIL_OPTIONS = [100, 200, 500, 1000] as const;

export function LogViewerModal({
  title,
  description,
  filename,
  idPrefix,
  closeId,
  onClose,
  load,
}: {
  title: string;
  description: string;
  filename: string;
  idPrefix: string;
  closeId?: string;
  onClose: () => void;
  load: (tail: number) => Promise<string>;
}) {
  const [tail, setTail] = useState(200);
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setLogs((await load(tail)) || "No logs available.");
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Failed to load logs");
    } finally {
      setLoading(false);
    }
  }, [load, tail]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refresh]);

  const download = () => {
    const url = URL.createObjectURL(new Blob([logs], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <ModalOverlay onClose={onClose}>
      <Card
        aria-labelledby={`${idPrefix}-title`}
        aria-modal="true"
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden"
        id={`${idPrefix}-modal`}
        role="dialog"
      >
        <CardHeader className="space-y-3 border-b border-border/70 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle id={`${idPrefix}-title`}>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
            <Button id={closeId ?? `${idPrefix}-close`} onClick={onClose} variant="outline">
              Close
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex min-h-11 items-center gap-2 text-xs text-muted-foreground">
              Tail
              <select
                className="min-h-11 rounded-md border border-border bg-background px-3 text-foreground"
                id={`${idPrefix}-tail`}
                onChange={(event) => setTail(Number(event.target.value))}
                value={tail}
              >
                {TAIL_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
            <Button className="gap-2" disabled={loading} onClick={() => void refresh()} variant="outline">
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", loading && "animate-spin")} />
              Refresh
            </Button>
            <Button
              aria-pressed={autoRefresh}
              onClick={() => setAutoRefresh((value) => !value)}
              variant={autoRefresh ? "success" : "outline"}
            >
              Auto-refresh {autoRefresh ? "on" : "off"}
            </Button>
            <Button className="gap-2" disabled={!logs} onClick={download} variant="outline">
              <Download aria-hidden="true" className="h-4 w-4" />
              Download
            </Button>
          </div>
        </CardHeader>
        <CardContent className="overflow-auto p-4">
          <pre
            aria-live="polite"
            className="min-h-48 whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-[#080b0f] p-3 font-mono text-xs text-foreground sm:text-sm"
            id={`${idPrefix}-content`}
          >
            {loading && !logs ? "Loading logs..." : error || logs || "No logs available."}
          </pre>
        </CardContent>
      </Card>
    </ModalOverlay>
  );
}
