// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, abortPrivateRequests, api, onUnauthorized, resetClientSession, setCsrfToken } from "./api";

type Call = { url: string; init: RequestInit };

function mockFetch(handler: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const call = { url, init };
      calls.push(call);
      return handler(call);
    }),
  );
  return calls;
}

const json = (body: unknown, status = 200) => Response.json(body, { status });
const header = (call: Call, name: string) => new Headers(call.init.headers).get(name);

beforeEach(() => resetClientSession());
afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("fetches a CSRF token once and sends it on state-changing requests only", async () => {
    const calls = mockFetch(({ url }) =>
      url.endsWith("/auth/csrf") ? json({ csrf_token: "tok-1" }) : json({ id: "c1", name: "x" }, 201),
    );
    await api.courses.create({ name: "x" });
    await api.courses.create({ name: "y" });
    await api.courses.list();
    expect(calls.map((c) => c.url)).toEqual(["/api/auth/csrf", "/api/courses", "/api/courses", "/api/courses"]);
    expect(header(calls[1], "x-csrf-token")).toBe("tok-1");
    expect(header(calls[3], "x-csrf-token")).toBeNull();
    expect(calls[1].init.credentials).toBe("same-origin");
  });

  it("refreshes a stale CSRF token once and retries", async () => {
    setCsrfToken("stale");
    let attempts = 0;
    const calls = mockFetch(({ url }) => {
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "fresh" });
      attempts += 1;
      return attempts === 1 ? json({ error: { code: "csrf_failed", message: "bad" } }, 403) : json({ id: "c1" }, 201);
    });
    await api.courses.create({ name: "x" });
    expect(calls.map((c) => header(c, "x-csrf-token"))).toEqual(["stale", null, "fresh"]);
  });

  it("does not retry other 403s", async () => {
    setCsrfToken("tok");
    mockFetch(() => json({ error: { code: "forbidden", message: "Administrator access is required." } }, 403));
    await expect(api.admin.users()).rejects.toMatchObject({ status: 403, code: "forbidden" });
  });

  it("reports signed-out 401s from private endpoints, but not from the auth endpoints", async () => {
    const handler = vi.fn();
    const unsubscribe = onUnauthorized(handler);
    mockFetch(({ url }) =>
      json({ error: { code: url.includes("/auth/") ? "invalid_credentials" : "session_expired", message: "x" } }, 401),
    );
    await expect(api.courses.list()).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
    setCsrfToken("tok");
    await expect(api.auth.login({ email: "a@b.c", password: "p", remember_me: false })).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(handler).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("stores the new session's CSRF token after signing in and forgets it after signing out", async () => {
    const calls = mockFetch(({ url }) => {
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "anonymous" });
      if (url.endsWith("/auth/login")) return json({ user: { id: "u1" }, csrf_token: "session-bound" });
      if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
      return json({ id: "c1" }, 201);
    });
    await api.auth.login({ email: "a@b.c", password: "correct horse battery", remember_me: true });
    await api.courses.create({ name: "x" });
    await api.auth.logout();
    await api.courses.create({ name: "y" });
    expect(calls.map((c) => [c.url, header(c, "x-csrf-token")])).toEqual([
      ["/api/auth/csrf", null],
      ["/api/auth/login", "anonymous"],
      ["/api/courses", "session-bound"],
      ["/api/auth/logout", "session-bound"],
      ["/api/auth/csrf", null],
      ["/api/courses", "anonymous"],
    ]);
  });

  it("cancels in-flight private requests on sign-out", async () => {
    mockFetch(
      ({ init }) =>
        new Promise<Response>((_, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const pending = api.courses.list();
    abortPrivateRequests();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("turns network failures into a friendly error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    await expect(api.courses.list()).rejects.toMatchObject({ code: "network_error" });
  });
});
