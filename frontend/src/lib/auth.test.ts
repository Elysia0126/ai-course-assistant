import { describe, expect, it } from "vitest";

import { checkNewPassword, displayName, isPublicPath, passwordLength, safeNextPath } from "./auth";

describe("safeNextPath (open-redirect guard)", () => {
  it("keeps same-site paths with their query and hash", () => {
    expect(safeNextPath("/courses/abc/ask?x=1#top")).toBe("/courses/abc/ask?x=1#top");
    expect(safeNextPath("/")).toBe("/");
  });

  it.each([
    ["https://evil.example/phish"],
    ["//evil.example"],
    ["/\\evil.example"],
    ["\\\\evil.example"],
    ["/\t/evil.example"],
    ["javascript:alert(1)"],
    ["evil.example"],
    ["/login?next=/x"], // would loop back to the sign-in page
    ["/reset-password#token=abc"],
    ["/api/auth/logout"],
    [""],
    [null],
    [undefined],
  ])("rejects %j", (value) => {
    expect(safeNextPath(value as string | null | undefined)).toBe("/");
  });
});

describe("password rules (mirroring the server)", () => {
  it("counts Unicode characters, not UTF-16 units", () => {
    expect("🔒".length).toBe(2);
    expect(passwordLength("🔒")).toBe(1);
  });

  it("asks for length and a matching confirmation, nothing else", () => {
    expect(checkNewPassword("seven!!", "seven!!").password).toMatch(/at least 8 characters \(7 so far\)/);
    expect(checkNewPassword("8 chars!", "8 chars!")).toEqual({});
    expect(checkNewPassword("我的课程助手密码", "我的课程助手密码")).toEqual({}); // 8 characters
    expect(checkNewPassword("correct horse battery staple", "correct horse battery stapl")).toEqual({
      password_confirm: "The passwords don't match.",
    });
    expect(checkNewPassword("all lower case, no digits ok", "all lower case, no digits ok")).toEqual({});
    expect(checkNewPassword("x".repeat(129), "x".repeat(129)).password).toMatch(/at most 128/);
  });
});

describe("helpers", () => {
  it("knows which pages are public", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/reset-password")).toBe(true);
    expect(isPublicPath("/loginx")).toBe(false);
    expect(isPublicPath("/courses/1")).toBe(false);
  });

  it("derives a display name", () => {
    expect(displayName({ display_name: " Ada ", email: "ada@example.com" })).toBe("Ada");
    expect(displayName({ display_name: null, email: "grace@example.com" })).toBe("grace");
  });
});
