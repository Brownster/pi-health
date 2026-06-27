import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  status,
  actions,
}: {
  title: string;
  description?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="break-words font-mono text-xl font-semibold text-foreground sm:text-[22px]">
            {title}
          </h1>
          {status}
        </div>
        {description ? (
          <div className="mt-1.5 font-mono text-xs text-dim sm:text-[13px]">{description}</div>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
