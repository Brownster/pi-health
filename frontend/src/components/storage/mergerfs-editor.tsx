import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Eye,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchDiskInventory } from "@/lib/disks";
import {
  applyPluginConfig,
  previewPluginConfig,
  savePluginConfig,
} from "@/lib/storage-plugins";

const CREATE_POLICIES: { value: string; label: string }[] = [
  { value: "epmfs", label: "epmfs — existing path, most free space (default)" },
  { value: "eplfs", label: "eplfs — existing path, least free space" },
  { value: "mfs", label: "mfs — most free space" },
  { value: "lfs", label: "lfs — least free space" },
  { value: "rand", label: "rand — random branch" },
  { value: "ff", label: "ff — first found" },
];

const PRESETS: { value: string; label: string }[] = [
  { value: "linux_6_6_plus", label: "Linux 6.6+" },
  { value: "linux_6_5_mmap", label: "Linux ≤ 6.5 + mmap" },
  { value: "linux_6_5_no_mmap", label: "Linux ≤ 6.5, no mmap" },
];

const MIN_FREE_RE = /^\d+(\.\d+)?[KMGT]?$/i;

interface PoolDraft {
  id: string;
  name: string;
  mount_point: string;
  branches: string[];
  create_policy: string;
  preset: string;
  min_free_space: string;
  options: string;
  enabled: boolean;
}

function emptyPool(): PoolDraft {
  return {
    id: `pool-${Date.now()}`,
    name: "",
    mount_point: "",
    branches: [],
    create_policy: "epmfs",
    preset: "linux_6_5_no_mmap",
    min_free_space: "4G",
    options: "",
    enabled: true,
  };
}

export function MergerfsEditor({
  pluginId,
  config,
  onSaved,
}: {
  pluginId: string;
  config: Record<string, unknown>;
  onSaved: () => void;
}) {
  const [candidates, setCandidates] = useState<string[] | null>(null);
  const [pools, setPools] = useState<PoolDraft[]>([]);
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<"" | "preview" | "save" | "apply">("");
  const [confirmApply, setConfirmApply] = useState(false);

  useEffect(() => {
    let active = true;
    const existing = ((config.pools as Record<string, unknown>[]) ?? []).map((pool) => ({
      ...emptyPool(),
      id: String(pool.id ?? `pool-${Math.random()}`),
      name: String(pool.name ?? ""),
      mount_point: String(pool.mount_point ?? ""),
      branches: Array.isArray(pool.branches) ? pool.branches.map((b) => String(b)) : [],
      create_policy: String(pool.create_policy ?? "epmfs"),
      preset: String(pool.preset ?? "linux_6_5_no_mmap"),
      min_free_space: String(pool.min_free_space ?? "4G"),
      options: String(pool.options ?? ""),
      enabled: pool.enabled !== false,
    }));
    setPools(existing);
    setDirty(false);
    setPreview(null);
    setErrors([]);

    fetchDiskInventory()
      .then((inventory) => {
        if (!active) return;
        const mounts = new Set<string>();
        for (const disk of inventory.disks) {
          for (const entry of [disk, ...disk.partitions]) {
            if (entry.mountpoint?.startsWith("/mnt/")) mounts.add(entry.mountpoint);
          }
        }
        setCandidates([...mounts].sort());
      })
      .catch(() => setCandidates([]));
    return () => {
      active = false;
    };
  }, [config]);

  const updatePool = (id: string, patch: Partial<PoolDraft>) => {
    setDirty(true);
    setPreview(null);
    setNotice(null);
    setPools((prev) =>
      prev.map((pool) => {
        if (pool.id !== id) return pool;
        const next = { ...pool, ...patch };
        // Default the mount point to /mnt/<name> until the user edits it.
        if (patch.name !== undefined && (pool.mount_point === "" || pool.mount_point === `/mnt/${pool.name}`)) {
          next.mount_point = patch.name ? `/mnt/${patch.name}` : "";
        }
        return next;
      }),
    );
  };

  const toggleBranch = (id: string, branch: string) => {
    setDirty(true);
    setPreview(null);
    setNotice(null);
    setPools((prev) =>
      prev.map((pool) =>
        pool.id === id
          ? {
              ...pool,
              branches: pool.branches.includes(branch)
                ? pool.branches.filter((b) => b !== branch)
                : [...pool.branches, branch],
            }
          : pool,
      ),
    );
  };

  const moveBranch = (id: string, index: number, direction: -1 | 1) => {
    setDirty(true);
    setPreview(null);
    setNotice(null);
    setPools((prev) => prev.map((pool) => {
      if (pool.id !== id) return pool;
      const target = index + direction;
      if (target < 0 || target >= pool.branches.length) return pool;
      const branches = [...pool.branches];
      [branches[index], branches[target]] = [branches[target], branches[index]];
      return { ...pool, branches };
    }));
  };

  const addPool = () => {
    setDirty(true);
    setPreview(null);
    setNotice(null);
    setPools((prev) => [...prev, emptyPool()]);
  };

  const removePool = (id: string) => {
    setDirty(true);
    setPreview(null);
    setNotice(null);
    setPools((prev) => prev.filter((pool) => pool.id !== id));
  };

  const poolErrors = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const pool of pools) {
      const list: string[] = [];
      if (!pool.name.trim()) list.push("Name is required.");
      if (new Set(pool.branches).size < 2) list.push("Add at least two distinct branches.");
      if (!pool.mount_point.startsWith("/mnt/") || pool.mount_point.includes("..")) {
        list.push("Mount point must be a safe path under /mnt/.");
      }
      if (!MIN_FREE_RE.test(pool.min_free_space.trim())) list.push("Min free space must look like 4G, 500M, 1T.");
      if (list.length) map[pool.id] = list;
    }
    return map;
  }, [pools]);

  const buildConfig = (): Record<string, unknown> => ({
    ...config,
    enabled: true,
    pools: pools.map((pool) => ({
      id: pool.id,
      name: pool.name,
      mount_point: pool.mount_point,
      branches: pool.branches,
      create_policy: pool.create_policy,
      preset: pool.preset,
      min_free_space: pool.min_free_space,
      options: pool.options,
      enabled: pool.enabled,
    })),
  });

  const draftErrors = Object.values(poolErrors).flat();

  const onPreview = async () => {
    if (draftErrors.length) {
      setErrors(draftErrors);
      return;
    }
    setBusy("preview");
    setErrors([]);
    setNotice(null);
    try {
      setPreview(await previewPluginConfig(pluginId, buildConfig()));
    } catch (error) {
      setErrors([error instanceof Error ? error.message : "Preview failed"]);
    } finally {
      setBusy("");
    }
  };

  const onSave = async () => {
    if (draftErrors.length) {
      setErrors(draftErrors);
      return;
    }
    setBusy("save");
    setErrors([]);
    setNotice(null);
    const result = await savePluginConfig(pluginId, buildConfig());
    setBusy("");
    if (result.ok) {
      setDirty(false);
      setNotice("Saved. Apply to (re)mount pools.");
      onSaved();
    } else {
      setErrors(result.details.length ? result.details : [result.error ?? "Save failed"]);
    }
  };

  const onApply = async () => {
    setConfirmApply(false);
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

  if (!candidates) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Loading disks...
      </p>
    );
  }

  return (
    <div className="space-y-4" data-mergerfs-editor>
      {pools.map((pool) => (
        <div className="space-y-3 rounded-lg border border-border/70 p-3" data-pool-editor={pool.id} key={pool.id}>
          <div className="flex items-center gap-2">
            <input
              aria-label="Pool name"
              className="h-9 flex-1 rounded-md border border-input bg-background px-2 text-sm"
              data-pool-name={pool.id}
              onChange={(e) => updatePool(pool.id, { name: e.target.value })}
              placeholder="pool name"
              value={pool.name}
            />
            <label className="flex items-center gap-1 text-xs text-muted-foreground">
              <input
                checked={pool.enabled}
                data-pool-enabled={pool.id}
                onChange={(e) => updatePool(pool.id, { enabled: e.target.checked })}
                type="checkbox"
              />
              enabled
            </label>
            <Button
              aria-label="Remove pool"
              data-pool-remove={pool.id}
              onClick={() => removePool(pool.id)}
              size="icon"
              title="Remove pool"
              variant="ghost"
            >
              <Trash2 aria-hidden="true" className="h-4 w-4" />
            </Button>
          </div>

          <input
            aria-label="Mount point"
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
            onChange={(e) => updatePool(pool.id, { mount_point: e.target.value })}
            placeholder="/mnt/<name>"
            value={pool.mount_point}
          />

          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Branches (at least 2, in priority order)</p>
            {pool.branches.length ? (
              <ol className="divide-y divide-border overflow-hidden rounded-md border border-border" data-pool-branches={pool.id}>
                {pool.branches.map((branch, index) => (
                  <li className="flex min-h-10 items-center gap-2 bg-muted/15 px-2" key={branch}>
                    <span className="w-5 shrink-0 text-center font-mono text-[10px] text-dim">{index + 1}</span>
                    <code className="min-w-0 flex-1 truncate text-xs" title={branch}>{branch}</code>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button aria-label={`Move ${branch} up`} disabled={index === 0} onClick={() => moveBranch(pool.id, index, -1)} size="icon" title="Move branch up" variant="ghost"><ArrowUp aria-hidden="true" className="h-3.5 w-3.5" /></Button>
                      <Button aria-label={`Move ${branch} down`} disabled={index === pool.branches.length - 1} onClick={() => moveBranch(pool.id, index, 1)} size="icon" title="Move branch down" variant="ghost"><ArrowDown aria-hidden="true" className="h-3.5 w-3.5" /></Button>
                      <Button aria-label={`Remove ${branch}`} onClick={() => toggleBranch(pool.id, branch)} size="icon" title="Remove branch" variant="ghost"><X aria-hidden="true" className="h-3.5 w-3.5" /></Button>
                    </div>
                  </li>
                ))}
              </ol>
            ) : null}
            <div className="flex flex-wrap gap-1.5 pt-1">
              {candidates
                .filter((mount) => !pool.branches.includes(mount))
                .map((mount) => (
                  <Button
                    data-pool-branch-add={`${pool.id}:${mount}`}
                    key={mount}
                    onClick={() => toggleBranch(pool.id, mount)}
                    size="sm"
                    variant="outline"
                  >
                    <Plus aria-hidden="true" className="mr-1 h-3.5 w-3.5" />
                    {mount}
                  </Button>
                ))}
            </div>
            <div className="flex gap-2 pt-1">
              <input
                aria-label="Custom branch path or glob"
                className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs"
                onChange={(e) => setCustom((prev) => ({ ...prev, [pool.id]: e.target.value }))}
                placeholder="/mnt/disk*/data (glob)"
                value={custom[pool.id] ?? ""}
              />
              <Button
                onClick={() => {
                  const value = (custom[pool.id] ?? "").trim();
                  if (value) {
                    toggleBranch(pool.id, value);
                    setCustom((prev) => ({ ...prev, [pool.id]: "" }));
                  }
                }}
                size="sm"
                variant="outline"
              >
                Add
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Create policy</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => updatePool(pool.id, { create_policy: e.target.value })}
                value={pool.create_policy}
              >
                {CREATE_POLICIES.map((policy) => (
                  <option key={policy.value} value={policy.value}>
                    {policy.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Options preset</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => updatePool(pool.id, { preset: e.target.value })}
                value={pool.preset}
              >
                {PRESETS.map((preset) => (
                  <option key={preset.value} value={preset.value}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Min free space</span>
              <input
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => updatePool(pool.id, { min_free_space: e.target.value })}
                value={pool.min_free_space}
              />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Extra options</span>
              <input
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => updatePool(pool.id, { options: e.target.value })}
                placeholder="comma,separated"
                value={pool.options}
              />
            </label>
          </div>

          {poolErrors[pool.id] ? (
            <ul className="space-y-1" data-pool-errors={pool.id}>
              {poolErrors[pool.id].map((message) => (
                <li className="flex items-start gap-1.5 text-xs text-warning" key={message}>
                  <AlertTriangle aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}

      <Button
        className="gap-1.5"
        data-pool-add
        onClick={addPool}
        size="sm"
        variant="outline"
      >
        <Plus aria-hidden="true" className="h-4 w-4" />
        Add pool
      </Button>

      {errors.length ? (
        <ul className="space-y-1 rounded-md bg-danger/10 p-2" data-mergerfs-errors>
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

      {preview ? (
        <section aria-labelledby="mergerfs-preview-title" className="overflow-hidden rounded-md border border-border" data-mergerfs-preview>
          <div className="border-b border-border bg-muted/20 px-3 py-2">
            <h3 className="font-mono text-xs font-semibold" id="mergerfs-preview-title">Managed fstab preview</h3>
          </div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all p-3 text-xs text-muted-foreground">{preview}</pre>
        </section>
      ) : null}

      {confirmApply ? (
        <div className="space-y-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-xs" data-apply-confirm>
          <p className="flex items-center gap-1.5 font-medium text-warning">
            <AlertTriangle aria-hidden="true" className="h-4 w-4" />
            Apply rewrites the managed /etc/fstab section and (re)mounts pools. Disabled pools are
            unmounted and removed from the section. Continue?
          </p>
          <div className="flex gap-2">
            <Button data-apply-confirm-yes onClick={() => void onApply()} size="sm" variant="danger">
              Apply changes
            </Button>
            <Button onClick={() => setConfirmApply(false)} size="sm" variant="outline">
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button className="gap-1.5" data-mergerfs-preview-open disabled={busy !== "" || Boolean(draftErrors.length)} onClick={() => void onPreview()} size="sm" variant="outline">
          <Eye aria-hidden="true" className="h-3.5 w-3.5" />
          {busy === "preview" ? "Previewing..." : "Preview"}
        </Button>
        <Button data-mergerfs-save disabled={busy !== "" || Boolean(draftErrors.length)} onClick={() => void onSave()} size="sm">
          {busy === "save" ? "Saving..." : "Save"}
        </Button>
        <Button
          data-mergerfs-apply
          disabled={busy !== "" || dirty || Boolean(draftErrors.length)}
          onClick={() => setConfirmApply(true)}
          size="sm"
          variant="secondary"
        >
          {busy === "apply" ? "Applying..." : "Apply"}
        </Button>
        {dirty ? <span className="text-xs text-warning">Save changes before applying.</span> : null}
      </div>
    </div>
  );
}
