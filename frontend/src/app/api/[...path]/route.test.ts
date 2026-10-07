// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST, isCrossOrigin } from "./route";

const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("API proxy", () => {
  it("forwards to BACKEND_URL with the server-side token and streams the response back", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend:8000/");
    vi.stubEnv("APP_API_TOKEN", "s3cret");
    const fetchMock = vi.fn(async () =>
      new Response("event: token\ndata: {}\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream", "cache-control": "no-cache, no-transform", "set-cookie": "x=1" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new NextRequest("http://app.test/api/courses/a%20b?x=1", { headers: { host: "app.test" } }), ctx(["courses", "a b"]));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/courses/a%20b?x=1");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer s3cret");
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("set-cookie")).toBeNull(); // only whitelisted headers pass through
    expect(await response.text()).toContain("event: token");
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
    expect((await response.json()).error.code).toBe("backend_unavailable");
  });
});
