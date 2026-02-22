import { Laptop, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type ThemeMode, useTheme } from "@/components/theme/theme-provider";
import { cn } from "@/lib/utils";

const options: Array<{ label: string; mode: ThemeMode; icon: typeof Sun }> = [
  { label: "Light", mode: "light", icon: Sun },
  { label: "Dark", mode: "dark", icon: Moon },
  { label: "System", mode: "system", icon: Laptop },
];

export function ThemeModeToggle() {
  const { mode, setMode } = useTheme();

  return (
    <div
      className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted/70 p-1"
      role="group"
      aria-label="Theme mode"
    >
      {options.map(({ label, mode: optionMode, icon: Icon }) => (
        <Button
          key={optionMode}
          aria-pressed={mode === optionMode}
          className={cn(
            "min-h-11 gap-2 px-3 text-xs sm:text-sm",
            mode === optionMode && "bg-background text-foreground shadow",
          )}
          onClick={() => setMode(optionMode)}
          variant="ghost"
        >
          <Icon aria-hidden="true" className="h-4 w-4" />
          <span>{label}</span>
        </Button>
      ))}
    </div>
  );
}
