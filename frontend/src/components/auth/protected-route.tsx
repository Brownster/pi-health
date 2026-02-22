import { useEffect, type PropsWithChildren } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const LOGIN_PATH = "/login.html";

function redirectToLogin(): void {
  window.location.replace(LOGIN_PATH);
}

export function ProtectedRoute({ children }: PropsWithChildren) {
  const { state, error, refresh } = useAuth();

  useEffect(() => {
    if (state === "unauthenticated") {
      redirectToLogin();
    }
  }, [state]);

  if (state === "loading") {
    return (
      <section className="flex min-h-[40vh] items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Checking session</CardTitle>
            <CardDescription>
              Verifying your Pi-Health login before opening this route.
            </CardDescription>
          </CardHeader>
        </Card>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="flex min-h-[40vh] items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Session check failed</CardTitle>
            <CardDescription>
              {error || "Unable to verify your session right now."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={() => void refresh()}>Retry</Button>
            <Button onClick={redirectToLogin} variant="outline">
              Open Login
            </Button>
          </CardContent>
        </Card>
      </section>
    );
  }

  if (state === "unauthenticated") {
    return (
      <section className="flex min-h-[40vh] items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Redirecting to login</CardTitle>
            <CardDescription>
              This route requires an authenticated session.
            </CardDescription>
          </CardHeader>
        </Card>
      </section>
    );
  }

  return <>{children}</>;
}
