import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/app-header";
import { AuthProvider } from "@/components/auth-context";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { safeNextPath } from "@/lib/auth";
import { getSession } from "@/lib/server-auth";

/**
 * Every page in this group (dashboard, courses, admin) needs a signed-in user. The check runs on the
 * server against FastAPI before anything renders; the pages' data then comes from API calls that FastAPI
 * authorises again, one by one.
 */
export default async function SignedInLayout({ children }: { children: ReactNode }) {
  const session = await getSession();
  if (session.status === "unavailable") {
    return (
      <>
        <AppHeader />
        <main className="flex flex-1 flex-col">
          <ServiceUnavailable />
        </main>
      </>
    );
  }
  if (session.status !== "authenticated") {
    const requested = (await headers()).get("x-aica-pathname");
    const params = new URLSearchParams({ next: safeNextPath(requested) });
    if (session.status === "expired") params.set("reason", "expired");
    redirect(`/login?${params}`);
  }
  return (
    <AuthProvider user={session.user}>
      <AppHeader />
      <main className="flex flex-1 flex-col">{children}</main>
    </AuthProvider>
  );
}
