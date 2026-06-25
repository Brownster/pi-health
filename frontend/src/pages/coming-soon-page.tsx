import type { ComponentType } from "react";
import { Clock } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface ComingSoonOptions {
  title: string;
  legacyHref: string;
  description?: string;
}

/**
 * Phase 3 (PH3-001) placeholder. Reserves a v2 route behind the auth guard and
 * shell so each core-management page can be rolled out incrementally, while the
 * legacy page remains the functional source until that ticket lands.
 */
export function createComingSoonPage({
  title,
  legacyHref,
  description,
}: ComingSoonOptions): ComponentType {
  function ComingSoonPage() {
    return (
      <section className="space-y-4 sm:space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
              <Clock aria-hidden="true" className="h-5 w-5 text-primary" />
              {title}
            </CardTitle>
            <CardDescription>
              {description ?? `The v2 ${title} page is part of the Phase 3 core-management migration.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              This route is reserved in the v2 shell. The legacy page remains the functional
              source until this page is migrated.
            </p>
            <div className="flex flex-wrap gap-2">
              <a
                className={buttonVariants({ variant: "outline" })}
                data-legacy-href={legacyHref}
                href={legacyHref}
              >
                Open Legacy {title}
              </a>
            </div>
          </CardContent>
        </Card>
      </section>
    );
  }

  ComingSoonPage.displayName = `ComingSoonPage(${title})`;
  return ComingSoonPage;
}
