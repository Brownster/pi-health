import { ArrowRight, ShieldCheck, Smartphone, TabletSmartphone } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const scopeItems = [
  {
    title: "Routing Foundation",
    detail: "Flask + /v2 integration and hybrid runtime switches (PH1-003 to PH1-004).",
    icon: ArrowRight,
  },
  {
    title: "Auth Continuity",
    detail: "Reuse current session and /api/auth/check model in v2 shell (PH1-005).",
    icon: ShieldCheck,
  },
  {
    title: "Mobile Baseline",
    detail: "No horizontal overflow and touch-first controls at phone/tablet widths.",
    icon: Smartphone,
  },
  {
    title: "Tablet Coverage",
    detail: "Responsive shell validated for 768x1024 with Playwright viewport matrix.",
    icon: TabletSmartphone,
  },
];

export function DashboardHomePage() {
  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Foundation Status</CardTitle>
          <CardDescription>
            React + Vite + TypeScript + Tailwind 4 workspace is now isolated in
            <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-xs">frontend/</code>
            and prepared for Flask-served `/v2` rollout.
          </CardDescription>
        </CardHeader>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
        {scopeItems.map(({ title, detail, icon: Icon }) => (
          <Card key={title}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm sm:text-base">
                <Icon aria-hidden="true" className="h-4 w-4 text-primary" />
                <span>{title}</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
