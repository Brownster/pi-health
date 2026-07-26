import { CheckCircle2, Download, ListVideo, Pause, PlayCircle, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatBytes, formatDuration, formatPercent, formatRate } from "@/lib/format";
import type {
  ActivityDownload,
  ActivityQueue,
  ActivitySnapshot,
  ActivityStream,
} from "@/lib/activity";
import { cn } from "@/lib/utils";

function ProgressBar({ percent, tone }: { percent: number | null; tone: string }) {
  return (
    <div
      aria-hidden="true"
      className="mt-2 h-1 overflow-hidden rounded-full bg-border"
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", tone)}
        style={{ width: `${Math.max(0, Math.min(percent ?? 0, 100))}%` }}
      />
    </div>
  );
}

function StreamRow({ stream }: { stream: ActivityStream }) {
  const Icon = stream.is_paused ? Pause : PlayCircle;
  const who = [stream.user, stream.client || stream.device].filter(Boolean).join(" · ");
  return (
    <li className="min-w-0 border-t border-divider py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-start gap-3">
        <Icon
          aria-hidden="true"
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            stream.is_paused ? "text-muted-foreground" : "text-success",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline justify-between gap-2">
            <p className="min-w-0 truncate text-sm text-foreground" title={stream.title}>
              {stream.title}
            </p>
            <span className="shrink-0 font-mono text-[10px] text-dim">
              {formatPercent(stream.progress_percent, 0)}
            </span>
          </div>
          {stream.subtitle ? (
            <p className="truncate text-xs text-muted-foreground">{stream.subtitle}</p>
          ) : null}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {who ? <span className="font-mono text-[10px] text-dim">{who}</span> : null}
            {stream.is_transcoding ? (
              <Badge
                tone="warning"
                title={stream.transcode_reason ?? "Transcoding uses far more CPU than direct play"}
              >
                transcoding
              </Badge>
            ) : stream.play_method ? (
              <Badge tone="success">{stream.play_method.toLowerCase()}</Badge>
            ) : null}
            {stream.is_paused ? <Badge tone="neutral">paused</Badge> : null}
          </div>
          <ProgressBar
            percent={stream.progress_percent}
            tone={stream.is_paused ? "bg-dim" : "bg-success"}
          />
          {stream.duration_seconds ? (
            <p className="mt-1 font-mono text-[10px] text-dim">
              {formatDuration(stream.position_seconds)} of{" "}
              {formatDuration(stream.duration_seconds)}
            </p>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function DownloadRow({ download }: { download: ActivityDownload }) {
  const isMoving = (download.speed_bytes ?? 0) > 0;
  return (
    <li className="min-w-0 border-t border-divider py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <p className="min-w-0 truncate text-sm text-foreground" title={download.name}>
          {download.name}
        </p>
        <span className="shrink-0 font-mono text-[10px] text-dim">
          {formatPercent(download.progress_percent, 0)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Badge tone="neutral">{download.label || download.source}</Badge>
        <Badge tone={isMoving ? "info" : "neutral"}>{download.state}</Badge>
        {isMoving ? (
          <span className="font-mono text-[10px] text-info">{formatRate(download.speed_bytes)}</span>
        ) : null}
        {download.eta ? (
          <span className="font-mono text-[10px] text-dim">{download.eta} left</span>
        ) : null}
        {download.remaining_bytes !== null ? (
          <span className="font-mono text-[10px] text-dim">
            {formatBytes(download.remaining_bytes)} of {formatBytes(download.size_bytes)}
          </span>
        ) : null}
      </div>
      <ProgressBar percent={download.progress_percent} tone={isMoving ? "bg-info" : "bg-dim"} />
    </li>
  );
}

function QueueRow({ queue }: { queue: ActivityQueue }) {
  return (
    <li className="flex min-w-0 items-center justify-between gap-3 border-t border-divider py-2.5 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm text-foreground">{queue.label || queue.source}</span>
        {queue.problems > 0 ? (
          <Badge tone="warning" title="Items in this queue need attention">
            <TriangleAlert aria-hidden="true" className="h-3 w-3" />
            {queue.problems}
          </Badge>
        ) : null}
      </div>
      <span className="shrink-0 font-mono text-xs text-muted-foreground">
        {queue.total} queued
      </span>
    </li>
  );
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof PlayCircle;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center gap-1.5">
        <Icon aria-hidden="true" className="h-3.5 w-3.5 text-dim" />
        <span className="font-mono text-[11px] uppercase text-dim">{title}</span>
      </div>
      {children}
    </div>
  );
}

export function ActivityPanel({
  snapshot,
  error,
}: {
  snapshot: ActivitySnapshot | null;
  error: string | null;
}) {
  const totals = snapshot?.totals;
  const unreachable = (snapshot?.services ?? []).filter((service) => !service.reachable);
  const isIdle =
    snapshot !== null &&
    totals !== undefined &&
    totals.streams === 0 &&
    totals.downloads === 0 &&
    totals.queued === 0;

  return (
    <Card>
      <CardContent className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <PlayCircle aria-hidden="true" className="h-4 w-4 text-primary" />
            <h2 className="font-mono text-sm font-semibold">activity</h2>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {totals ? (
              <>
                <Badge tone={totals.streams > 0 ? "success" : "neutral"}>
                  {totals.streams} streaming
                </Badge>
                {totals.transcodes > 0 ? (
                  <Badge tone="warning">{totals.transcodes} transcoding</Badge>
                ) : null}
                <Badge tone={totals.downloads > 0 ? "info" : "neutral"}>
                  {totals.downloads} downloading
                </Badge>
                {totals.download_speed > 0 ? (
                  <Badge tone="info">{formatRate(totals.download_speed)}</Badge>
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {error ? (
          <p className="mt-4 text-sm text-muted-foreground">
            <span className="text-warning">Activity unavailable:</span> {error}
          </p>
        ) : null}

        {!snapshot && !error ? (
          <p className="mt-4 text-sm text-muted-foreground">Checking media services...</p>
        ) : null}

        {isIdle ? (
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-success" />
            Nothing streaming or downloading right now.
          </div>
        ) : null}

        {snapshot && !isIdle ? (
          <div className="mt-4 space-y-5">
            {snapshot.streams.length ? (
              <Section icon={PlayCircle} title="now playing">
                <ul>
                  {snapshot.streams.map((stream) => (
                    <StreamRow key={`${stream.source}:${stream.title}:${stream.user}`} stream={stream} />
                  ))}
                </ul>
              </Section>
            ) : null}

            {snapshot.downloads.length ? (
              <Section icon={Download} title="downloading">
                <ul>
                  {snapshot.downloads.map((download) => (
                    <DownloadRow download={download} key={`${download.source}:${download.name}`} />
                  ))}
                </ul>
              </Section>
            ) : null}

            {snapshot.queues.some((queue) => queue.total > 0) ? (
              <Section icon={ListVideo} title="queues">
                <ul>
                  {snapshot.queues
                    .filter((queue) => queue.total > 0)
                    .map((queue) => (
                      <QueueRow key={queue.source} queue={queue} />
                    ))}
                </ul>
              </Section>
            ) : null}
          </div>
        ) : null}

        {unreachable.length ? (
          <details className="mt-4 border-t border-divider pt-3">
            <summary className="cursor-pointer font-mono text-[10px] uppercase text-dim hover:text-muted-foreground">
              {unreachable.length} service{unreachable.length === 1 ? "" : "s"} not reporting
            </summary>
            <ul className="mt-2 space-y-1">
              {unreachable.map((service) => (
                <li className="text-xs text-muted-foreground" key={service.id || service.name}>
                  <span className="text-foreground">{service.label || service.name}</span>
                  {service.detail ? ` — ${service.detail}` : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}
