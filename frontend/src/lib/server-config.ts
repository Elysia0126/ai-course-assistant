/**
 * Server-side runtime configuration shared by the /api proxy, proxy.ts and the session check. Read from
 * process.env at request time (never NEXT_PUBLIC_*), so none of it reaches the browser bundle.
 */

export function backendBase(): string {
  return (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

/** Shared secret that proves to FastAPI a request came through this server (not a user credential). */
export function apiToken(): string | undefined {
  return process.env.APP_API_TOKEN || undefined;
}

export function sessionCookieName(): string {
  return process.env.SESSION_COOKIE_NAME || "aica_session";
}

export function csrfCookieName(): string {
  return process.env.CSRF_COOKIE_NAME || "aica_csrf";
}

/** Number of reverse proxies in front of Next.js that append to X-Forwarded-For (0 = reached directly). */
export function trustedProxyCount(): number {
  const value = Number.parseInt(process.env.TRUSTED_PROXY_COUNT ?? "0", 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}
