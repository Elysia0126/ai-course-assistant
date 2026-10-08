// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST, clientAddress, filterCookieHeader, isCrossOrigin, sanitizeSetCookie } from "./route";

const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) });
const AUTH = new Set(["aica_session", "aica_csrf"]);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function upstreamWith(headers: [string, string][], body = "{}", status = 200) {
  const fetchMock = vi.fn(async () => new Response(body, { status, headers: new Headers(headers) }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("API proxy", () => {
  it("forwards to BACKEND_URL with the server-side token and streams the response back", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend:8000/");
    vi.stubEnv("APP_API_TOKEN", "s3cret");
    const fetchMock = upstreamWith([
      ["content-type", "text/event-stream"],
      ["cache-control", "no-store, no-transform"],
    ], "event: token\ndata: {}\n\n");

    const response = await GET(new NextRequest("http://app.test/api/courses/a%20b?x=1", { headers: { host: "app.test" } }), ctx(["courses", "a b"]));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/courses/a%20b?x=1");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer s3cret");
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-store, no-transform");
    expect(await response.text()).toContain("event: token");
  });

  it("forwards only the auth cookies, the CSRF header and the origin", async () => {
    const fetchMock = upstreamWith([["content-type", "application/json"]]);
    await POST(
      new NextRequest("http://app.test/api/courses", {
        method: "POST",
        headers: {
          host: "app.test",
          origin: "http://app.test",
          cookie: "aica_session=s1; analytics=track-me; aica_csrf=c1; theme=dark",
          "x-csrf-token": "c1",
          "x-forwarded-for": "203.0.113.9",
          authorization: "Bearer from-the-browser",
        },
        body: "{}",
      }),
      ctx(["courses"]),
    );
    const headers = new Headers((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers);
    expect(headers.get("cookie")).toBe("aica_session=s1; aica_csrf=c1");
    expect(headers.get("x-csrf-token")).toBe("c1");
    expect(headers.get("origin")).toBe("http://app.test");
    expect(headers.get("x-forwarded-for")).toBe("203.0.113.9");
    expect(headers.get("authorization")).toBeNull(); // a browser can't supply the service token
  });

  it("passes each Set-Cookie through separately, without Domain, and drops foreign cookies", async () => {
    upstreamWith([
      ["content-type", "application/json"],
      ["set-cookie", "aica_session=abc; expires=Thu, 08 Oct 2026 05:32:02 GMT; HttpOnly; Max-Age=43200; Path=/; SameSite=lax"],
      ["set-cookie", "aica_csrf=def; Domain=backend; HttpOnly; Path=/; SameSite=lax"],
      ["set-cookie", "tracker=1; Path=/"],
    ]);
    const response = await POST(
      new NextRequest("http://app.test/api/auth/login", { method: "POST", headers: { host: "app.test", origin: "http://app.test" }, body: "{}" }),
      ctx(["auth", "login"]),
    );
    expect(response.headers.getSetCookie()).toEqual([
      "aica_session=abc; expires=Thu, 08 Oct 2026 05:32:02 GMT; HttpOnly; Max-Age=43200; Path=/; SameSite=lax",
      "aica_csrf=def; HttpOnly; Path=/; SameSite=lax",
    ]);
  });

  it("keeps cookie deletions intact and makes responses private by default", async () => {
    upstreamWith(
      [
        ["content-type", "application/json"],
        ["set-cookie", 'aica_session=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Max-Age=0; Path=/; SameSite=lax'],
        ["retry-after", "42"],
      ],
      '{"error":{"code":"rate_limited"}}',
      429,
    );
    const response = await GET(new NextRequest("http://app.test/api/auth/me", { headers: { host: "app.test" } }), ctx(["auth", "me"]));
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("42");
    expect(response.headers.getSetCookie()[0]).toContain("Max-Age=0");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("refuses state-changing requests from other origins", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("http://app.test/api/courses", {
      method: "POST",
      headers: { host: "app.test", origin: "https://evil.example" },
      body: "{}",
    });
    expect(isCrossOrigin(request)).toBe(true);
    const response = await POST(request, ctx(["courses"]));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns a JSON error when the backend is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const response = await GET(new NextRequest("http://app.test/api/health", { headers: { host: "app.test" } }), ctx(["health"]));
    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect((await response.json()).error.code).toBe("backend_unavailable");
  });
});

describe("proxy helpers", () => {
  it("filters cookies by exact name", () => {
    expect(filterCookieHeader("aica_session=a; aica_session_x=b; xaica_csrf=c; aica_csrf=d", AUTH)).toBe("aica_session=a; aica_csrf=d");
    expect(filterCookieHeader("other=1", AUTH)).toBeNull();
    expect(filterCookieHeader(null, AUTH)).toBeNull();
  });

  it("strips Domain attributes in any case", () => {
    expect(sanitizeSetCookie("aica_csrf=x; DOMAIN=.internal; Path=/", AUTH)).toBe("aica_csrf=x; Path=/");
    expect(sanitizeSetCookie("evil=x; Path=/", AUTH)).toBeNull();
  });

  it("picks the client address according to TRUSTED_PROXY_COUNT", () => {
    const request = (xff: string) => new Request("http://app.test/", { headers: { "x-forwarded-for": xff } });
    expect(clientAddress(request("198.51.100.1"))).toBe("198.51.100.1");
    // Behind one appending reverse proxy, anything a client prepended is ignored.
    vi.stubEnv("TRUSTED_PROXY_COUNT", "1");
    expect(clientAddress(request("1.2.3.4, 198.51.100.1"))).toBe("198.51.100.1");
    vi.stubEnv("TRUSTED_PROXY_COUNT", "2");
    expect(clientAddress(request("1.2.3.4, 198.51.100.1, 10.0.0.2"))).toBe("198.51.100.1");
    expect(clientAddress(new Request("http://app.test/"))).toBeNull();
  });
});
