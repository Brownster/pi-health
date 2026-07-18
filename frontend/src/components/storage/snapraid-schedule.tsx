export interface ScheduleValue {
  sync_enabled: boolean;
  sync_cron: string;
  scrub_enabled: boolean;
  scrub_cron: string;
}

const PRESETS: { label: string; cron: string }[] = [
  { label: "Daily 03:00", cron: "0 3 * * *" },
  { label: "Daily 04:00", cron: "0 4 * * *" },
  { label: "Weekly Sun 04:00", cron: "0 4 * * 0" },
];

function CronRow({
  label,
  enabled,
  cron,
  onEnabled,
  onCron,
  testid,
}: {
  label: string;
  enabled: boolean;
  cron: string;
  onEnabled: (value: boolean) => void;
  onCron: (value: string) => void;
  testid: string;
}) {
  const presetValue = PRESETS.some((preset) => preset.cron === cron) ? cron : "custom";
  return (
    <div className="space-y-1.5" data-schedule-row={testid}>
      <label className="flex items-center gap-2 text-sm">
        <input
          checked={enabled}
          data-schedule-enabled={testid}
          onChange={(e) => onEnabled(e.target.checked)}
          type="checkbox"
        />
        {label}
      </label>
      {enabled ? (
        <div className="flex flex-wrap items-center gap-2 pl-6">
          <select
            aria-label={`${label} schedule`}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs"
            data-schedule-preset={testid}
            onChange={(e) => {
              if (e.target.value !== "custom") onCron(e.target.value);
            }}
            value={presetValue}
          >
            {PRESETS.map((preset) => (
              <option key={preset.cron} value={preset.cron}>
                {preset.label}
              </option>
            ))}
            <option value="custom">Custom cron</option>
          </select>
          <input
            aria-label={`${label} cron expression`}
            className="h-8 flex-1 rounded-md border border-input bg-background px-2 font-mono text-xs"
            data-schedule-cron={testid}
            onChange={(e) => onCron(e.target.value)}
            placeholder="0 3 * * *"
            value={cron}
          />
        </div>
      ) : null}
    </div>
  );
}

export function SnapraidSchedule({
  value,
  onChange,
}: {
  value: ScheduleValue;
  onChange: (next: ScheduleValue) => void;
}) {
  return (
    <div className="space-y-3" data-snapraid-schedule>
      <p className="font-mono text-xs uppercase text-muted-foreground">Schedule</p>
      <CronRow
        cron={value.sync_cron}
        enabled={value.sync_enabled}
        label="Automatic sync"
        onCron={(cron) => onChange({ ...value, sync_cron: cron })}
        onEnabled={(sync_enabled) => onChange({ ...value, sync_enabled })}
        testid="sync"
      />
      <CronRow
        cron={value.scrub_cron}
        enabled={value.scrub_enabled}
        label="Automatic scrub"
        onCron={(cron) => onChange({ ...value, scrub_cron: cron })}
        onEnabled={(scrub_enabled) => onChange({ ...value, scrub_enabled })}
        testid="scrub"
      />
      <p className="text-[0.7rem] text-muted-foreground">
        Save then Apply to (re)create the systemd timers.
      </p>
    </div>
  );
}
