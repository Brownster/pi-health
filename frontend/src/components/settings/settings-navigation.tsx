import { NavLink } from "react-router-dom";

import { APP_PATHS } from "@/app/route-contract";
import { cn } from "@/lib/utils";

const settingsLinks = [
  { label: "Overview", path: APP_PATHS.settings, end: true },
  { label: "Extensions", path: APP_PATHS.extensions, end: false },
];

export function SettingsNavigation() {
  return (
    <nav aria-label="Settings sections" className="border-b border-divider">
      <div className="flex min-w-0 items-end gap-5 overflow-x-auto">
        <span className="shrink-0 pb-3 font-mono text-[10px] uppercase text-dim">
          Settings / Advanced
        </span>
        {settingsLinks.map((link) => (
          <NavLink
            className={({ isActive }) =>
              cn(
                "relative shrink-0 border-b-2 px-1 pb-3 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                isActive
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )
            }
            end={link.end}
            key={link.path}
            to={link.path}
          >
            {link.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
