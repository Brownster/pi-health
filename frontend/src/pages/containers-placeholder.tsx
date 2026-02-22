import { Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function ContainersPlaceholderPage() {
  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wrench aria-hidden="true" className="h-5 w-5 text-primary" />
            Containers Pilot Placeholder
          </CardTitle>
          <CardDescription>
            This route is reserved for Phase 2 parity migration (`containers` first pilot).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            PH1-002 intentionally ships a route framework only. Functional container actions,
            polling, logs, and diagnostics remain on legacy pages until Phase 2.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => window.location.assign("/containers.html")}
              variant="outline"
            >
              Open Legacy Containers
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
