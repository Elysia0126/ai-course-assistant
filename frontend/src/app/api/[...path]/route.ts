/**
 * Same-origin proxy: the browser only ever talks to this Next.js server, which forwards /api/* to the
 * FastAPI backend. Benefits over calling the API directly:
 * - the backend URL is runtime configuration (BACKEND_URL), not baked into the client bundle;
 * - the backend can stay on a private network, optionally guarded by APP_API_TOKEN, which never
 *   reaches the browser;
 * - no CORS, and state-changing requests from other origins are refused (CSRF guard).
 * Request and response bodies are streamed, so uploads aren't buffered and SSE answers stay live.
 */
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "x-request-id"];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "content-length",
  "cache-control",
  "x-request-id",
  "x-accel-buffering",
];

function backendBase(): string {
  return (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, details: null } }, { status });
}

/** Mutating requests must come from this app's own pages. */
export function isCrossOrigin(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false; // non-browser clients (curl, scripts) don't send Origin
  try {
    return new URL(origin).host !== request.headers.get("host");
  } catch {
    return true;
  }
}

async function proxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }): Promise<Response> {
  if (isCrossOrigin(request)) return error(403, "cross_origin", "Cross-origin request refused.");

  const { path } = await params;
  const target = `${backendBase()}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (process.env.APP_API_TOKEN) headers.set("authorization", `Bearer ${process.env.APP_API_TOKEN}`);

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
      signal: request.signal, // the user pressing "Stop" cancels generation upstream
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
  responseHeaders.set("x-content-type-options", "nosniff");
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
