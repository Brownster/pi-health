import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Eye, HardDrive, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchDiskInventory } from "@/lib/disks";
import {
  applyPluginConfig,
  previewPluginConfig,
  savePluginConfig,
} from "@/lib/storage-plugins";

type Role = "none" | "data" | "parity";

interface Candidate {
  path: string; // mount point, e.g. /mnt/disk1
  uuid: string;
  name: string;
  sizeLabel: string | null;
  sizeGb: number | null;
}

interface Assignment {
  role: Role;
  content: boolean;
}

function parseSizeGb(size: string | null): number | null {
  if (!size) return null;
  const match = /([\d.]+)\s*([KMGTP])?i?B?/i.exec(size.trim());
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return null;
  const unit = (match[2] ?? "G").toUpperCase();
  const factor: Record<string, number> = { K: 1 / 1_000_000, M: 1 / 1000, G: 1, T: 1000, P: 1_000_000 };
  return value * (factor[unit] ?? 1);
}

function mountBasename(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export function SnapraidEditor({
  pluginId,
  config,
  onSaved,
}: {
  pluginId: string;
  config: Record<string, unknown>;
  onSaved: () => void;
}) {
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, Assignment>>({});
  const [percent, setPercent] = useState<string>("");
  const [ageDays, setAgeDays] = useState<string>("");
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "preview" | "save" | "apply">("");
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const scrub = (config.scrub as Record<string, unknown>) ?? {};
    setPercent(scrub.percent != null ? String(scrub.percent) : "");
    setAgeDays(scrub.age_days != null ? String(scrub.age_days) : "");

    const existing: Record<string, Assignment> = {};
    for (const drive of (config.drives as Record<string, unknown>[]) ?? []) {
      const path = String(drive.path ?? "");
      if (path) {
        existing[path] = {
          role: (drive.role as Role) ?? "data",
          content: Boolean(drive.content),
        };
      }
    }
    setAssignments(existing);

    fetchDiskInventory()
      .then((inventory) => {
        if (!active) return;
        const seen = new Set<string>();
        const found: Candidate[] = [];
        for (const disk of inventory.disks) {
          const entries = [disk, ...disk.partitions];
          for (const entry of entries) {
            const mount = entry.mountpoint ?? "";
            if (!mount.startsWith("/mnt/") || seen.has(mount)) continue;
            seen.add(mount);
            found.push({
              path: mount,
              uuid: entry.uuid ?? "",
              name: mountBasename(mount),
              sizeLabel: entry.size,
              sizeGb: parseSizeGb(entry.size),
            });
          }
        }
        setCandidates(found);
      })
      .catch((error) => {
        if (active) setLoadError(error instanceof Error ? error.message : "Failed to load disks");
      });
    return () => {
      active = false;
    };
  }, [config]);

  const setAssignment = (path: string, patch: Partial<Assignment>) => {
    setAssignments((prev) => {
      const base: Assignment = prev[path] ?? { role: "none", content: false };
      return { ...prev, [path]: { ...base, ...patch } };
    });
  };

  const assignedDrives = useMemo(() => {
    if (!candidates) return [];
    return candidates
      .map((candidate) => ({ candidate, assignment: assignments[candidate.path] }))
      .filter((row) => row.assignment && row.assignment.role !== "none");
  }, [candidates, assignments]);

  const warnings = useMemo(() => {
    const result: string[] = [];
    const data = assignedDrives.filter((row) => row.assignment.role === "data");
    const parity = assignedDrives.filter((row) => row.assignment.role === "parity");
    if (parity.length < 1) result.push("Add at least one parity drive.");
    if (data.length < 1) result.push("Add at least one data drive.");
    const largestData = Math.max(0, ...data.map((row) => row.candidate.sizeGb ?? 0));
    const smallestParity = Math.min(
      Infinity,
      ...parity.map((row) => row.candidate.sizeGb ?? Infinity),
    );
    if (parity.length && data.length && smallestParity < largestData) {
      result.push("A parity drive is smaller than the largest data drive; parity must be at least as large.");
    }
    if (assignedDrives.filter((row) => row.assignment.content).length < 2) {
      result.push("Store content files on at least two drives (recommended).");
    }
    return result;
  }, [assignedDrives]);

  const buildConfig = (): Record<string, unknown> => {
    const drives = assignedDrives.map((row) => ({
      id: row.candidate.name,
      name: row.candidate.name,
      path: row.candidate.path,
      uuid: row.candidate.uuid,
      role: row.assignment.role,
      content: row.assignment.content,
      ...(row.assignment.role === "parity" ? { parity_level: 1 } : {}),
    }));
    const scrub = { ...((config.scrub as Record<string, unknown>) ?? {}) };
    if (percent.trim() !== "") scrub.percent = Number(percent);
    if (ageDays.trim() !== "") scrub.age_days = Number(ageDays);
    return { ...config, enabled: true, drives, scrub };
  };

  const onPreview = async () => {
    setBusy("preview");
    setErrors([]);
    try {
      setPreview(await previewPluginConfig(pluginId, buildConfig()));
    } catch (error) {
      setErrors([error instanceof Error ? error.message : "Preview failed"]);
    } finally {
      setBusy("");
    }
  };

  const onSave = async () => {
    setBusy("save");
    setErrors([]);
    setNotice(null);
    const result = await savePluginConfig(pluginId, buildConfig());
    setBusy("");
    if (result.ok) {
      setNotice("Saved. Apply to write the SnapRAID config.");
      onSaved();
    } else {
      setErrors(result.details.length ? result.details : [result.error ?? "Save failed"]);
    }
  };

  const onApply = async () => {
    setBusy("apply");
    setErrors([]);
    setNotice(null);
    const result = await applyPluginConfig(pluginId);
    setBusy("");
    if (result.ok) {
      setNotice(result.message ?? "Applied.");
      onSaved();
    } else {
      setErrors([result.error ?? "Apply failed"]);
    }
  };

  if (loadError) {
    return <p className="text-sm text-danger">Could not load disks: {loadError}</p>;
  }
  if (!candidates) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Loading disks...
      </p>
    );
  }

  return (
    <div className="space-y-4" data-snapraid-editor>
      <div className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">Drives</p>
        {candidates.length ? (
          <ul className="space-y-2">
            {candidates.map((candidate) => {
              const assignment = assignments[candidate.path] ?? { role: "none", content: false };
              return (
                <li
                  className="flex flex-wrap items-center gap-2 rounded-md border border-border/70 p-2 text-sm"
                  data-drive={candidate.path}
                  key={candidate.path}
                >
                  <HardDrive aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">
                    {candidate.path}
                    <span className="ml-2 text-xs text-muted-foreground">{candidate.sizeLabel ?? ""}</span>
                  </span>
                  <select
                    aria-label={`Role for ${candidate.path}`}
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                    data-drive-role={candidate.path}
                    onChange={(e) => setAssignment(candidate.path, { role: e.target.value as Role })}
                    value={assignment.role}
                  >
                    <option value="none">Unassigned</option>
                    <option value="data">Data</option>
                    <option value="parity">Parity</option>
                  </select>
                  <label className="flex items-center gap-1 text-xs text-muted-foreground">
                    <input
                      checked={assignment.content}
                      data-drive-content={candidate.path}
                      disabled={assignment.role === "none"}
                      onChange={(e) => setAssignment(candidate.path, { content: e.target.checked })}
                      type="checkbox"
                    />
                    content
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            No mounted /mnt/* disks found. Mount data and parity disks first.
          </p>
        )}
      </div>

      {warnings.length ? (
        <ul className="space-y-1" data-snapraid-warnings>
          {warnings.map((warning) => (
            <li className="flex items-start gap-1.5 text-xs text-warning" key={warning}>
              <AlertTriangle aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {warning}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">Scrub percent</span>
          <input
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
            max={100}
            min={0}
            onChange={(e) => setPercent(e.target.value)}
            placeholder="8"
            type="number"
            value={percent}
          />
        </label>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">Scrub min age (days)</span>
          <input
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
            min={0}
            onChange={(e) => setAgeDays(e.target.value)}
            placeholder="10"
            type="number"
            value={ageDays}
          />
        </label>
      </div>

      {errors.length ? (
        <ul className="space-y-1 rounded-md bg-danger/10 p-2" data-snapraid-errors>
          {errors.map((message) => (
            <li className="text-xs font-medium text-danger" key={message}>
              {message}
            </li>
          ))}
        </ul>
      ) : null}

      {notice ? (
        <p className="text-xs font-medium text-success" role="status">
          {notice}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button className="gap-1.5" disabled={busy !== ""} onClick={() => void onPreview()} size="sm" variant="outline">
          <Eye aria-hidden="true" className="h-3.5 w-3.5" />
          Preview
        </Button>
        <Button data-snapraid-save disabled={busy !== ""} onClick={() => void onSave()} size="sm">
          {busy === "save" ? "Saving..." : "Save"}
        </Button>
        <Button
          data-snapraid-apply
          disabled={busy !== ""}
          onClick={() => void onApply()}
          size="sm"
          variant="secondary"
        >
          {busy === "apply" ? "Applying..." : "Apply"}
        </Button>
      </div>

      {preview !== null ? (
        <div className="space-y-1" data-snapraid-preview>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">snapraid.conf preview</p>
          <pre className="max-h-[24vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border/70 bg-muted/20 p-3 text-xs">
            {preview || "(empty)"}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
