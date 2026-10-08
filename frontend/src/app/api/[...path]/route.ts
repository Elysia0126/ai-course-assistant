/**
 * Same-origin proxy: the browser only ever talks to this Next.js server, which forwards /api/* to the
 * FastAPI backend. Benefits over calling the API directly:
 * - the backend URL is runtime configuration (BACKEND_URL), not baked into the client bundle;
 * - the backend can stay on a private network, guarded by APP_API_TOKEN, which never reaches the browser;
 * - cookies stay first-party: the session cookie is HttpOnly, host-only and SameSite on this origin.
 *
 * Only the auth cookies travel (both ways), Set-Cookie headers are passed one by one (never comma-joined)
 * without any Domain attribute, and every response is marked private/no-store. Request and response
 * bodies are streamed, so uploads aren't buffered and SSE answers stay live.
 */
import type { NextRequest } from "next/server";

import { apiToken, backendBase, csrfCookieName, sessionCookieName, trustedProxyCount } from "@/lib/server-config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// origin/referer let FastAPI run its own CSRF origin check; x-csrf-token is the synchronizer token.
const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "x-request-id", "x-csrf-token", "origin", "referer"];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "content-length",
  "cache-control",
  "retry-after",
  "x-request-id",
  "x-accel-buffering",
];

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, details: null } }, { status, headers: { "cache-control": "no-store" } });
}

function authCookies(): Set<string> {
  return new Set([sessionCookieName(), csrfCookieName()]);
}

/** Early refusal of obviously cross-site writes (FastAPI re-checks against APP_PUBLIC_URL). */
export function isCrossOrigin(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false; // FastAPI refuses state-changing requests that carry neither Origin nor Referer
  try {
    return new URL(origin).host !== request.headers.get("host");
  } catch {
    return true;
  }
}

/** Keep only our auth cookies from the browser's Cookie header. */
export function filterCookieHeader(header: string | null, allowed: Set<string>): string | null {
  if (!header) return null;
  const kept = header
    .split(";")
    .map((part) => part.trim())
    .filter((part) => allowed.has(part.split("=", 1)[0]));
  return kept.length ? kept.join("; ") : null;
}

/** Pass through only our auth cookies, and never with a Domain (they stay host-only on this origin). */
export function sanitizeSetCookie(value: string, allowed: Set<string>): string | null {
  const [pair, ...attributes] = value.split(";");
  if (!allowed.has(pair.split("=", 1)[0].trim())) return null;
  const kept = attributes.map((attribute) => attribute.trim()).filter((attribute) => attribute && !/^domain=/i.test(attribute));
  return [pair.trim(), ...kept].join("; ");
}

/**
 * The address FastAPI rate-limits on. Next.js sets X-Forwarded-For to the socket address unless a client
 * already sent one, so it is only trustworthy when TRUSTED_PROXY_COUNT reverse proxies in front of us
 * append to it (the n-th entry from the right is then the real client).
 */
export function clientAddress(request: Request): string | null {
  const entries = (request.headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  if (!entries.length) return null;
  return entries[Math.max(0, entries.length - Math.max(1, trustedProxyCount()))];
}

async function proxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }): Promise<Response> {
  if (isCrossOrigin(request)) return error(403, "origin_not_allowed", "Cross-origin request refused.");

  const { path } = await params;
  const target = `${backendBase()}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const allowedCookies = authCookies();

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const cookie = filterCookieHeader(request.headers.get("cookie"), allowedCookies);
  if (cookie) headers.set("cookie", cookie);
  const address = clientAddress(request);
  if (address) headers.set("x-forwarded-for", address);
  const token = apiToken();
  if (token) headers.set("authorization", `Bearer ${token}`);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by Node's fetch to stream a request body (large uploads).
      ...(hasBody ? { duplex: "half" } : {}),
      cache: "no-store",
      redirect: "manual",
      signal: request.signal, // the user pressing "Stop" (or signing out) cancels generation upstream
    } as RequestInit);
  } catch (err) {
    if ((err as Error).name === "AbortError") return new Response(null, { status: 499 });
    return error(502, "backend_unavailable", "The study service is unavailable. Check that the backend is running.");
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  for (const setCookie of upstream.headers.getSetCookie()) {
    const safe = sanitizeSetCookie(setCookie, allowedCookies);
    if (safe) responseHeaders.append("set-cookie", safe);
  }
  if (!responseHeaders.has("cache-control")) responseHeaders.set("cache-control", "private, no-store");
  responseHeaders.set("x-content-type-options", "nosniff");
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
