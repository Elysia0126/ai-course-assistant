import "server-only";

import { cookies } from "next/headers";
import { cache } from "react";

import { apiToken, backendBase, sessionCookieName } from "./server-config";
import type { User } from "./types";

export type SessionState =
  | { status: "authenticated"; user: User }
  | { status: "anonymous" } // no session cookie at all
  | { status: "expired" } // a cookie was sent but FastAPI no longer accepts it
  | { status: "unavailable" }; // the API couldn't be asked; don't pretend the user is signed out

/**
 * The real session check for server-rendered pages: ask FastAPI who owns the session cookie. Only the
 * session cookie and the proxy's service token are forwarded, and the answer is never cached (it's per
 * user). Deduplicated per render with React's cache(), so a layout and its page share one request.
 */
export const getSession = cache(async (): Promise<SessionState> => {
  const name = sessionCookieName();
  const token = (await cookies()).get(name)?.value;
  if (!token) return { status: "anonymous" };

  const headers: Record<string, string> = { cookie: `${name}=${token}`, accept: "application/json" };
  const serviceToken = apiToken();
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;
  try {
    const response = await fetch(`${backendBase()}/api/auth/me`, { headers, cache: "no-store" });
    if (response.status === 401) {
      const body = (await response.json().catch(() => null)) as { error?: { code?: string } } | null;
      // A rejected *service* token is a deployment problem, not a signed-out user.
      return body?.error?.code === "service_token_invalid" ? { status: "unavailable" } : { status: "expired" };
    }
    if (!response.ok) return { status: "unavailable" };
    return { status: "authenticated", user: (await response.json()) as User };
  } catch {
    return { status: "unavailable" };
  }
});
