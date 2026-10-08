import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginForm, RegisterForm } from "./auth-forms";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RegisterForm", () => {
  it("validates on the client before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<RegisterForm next="/" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "long enough passphrase" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "long enough passphrasE" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("The passwords don't match.")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a taken email next to the email field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/auth/csrf")
          ? Response.json({ csrf_token: "t" })
          : Response.json({ error: { code: "email_taken", message: "An account with this email already exists." } }, { status: 409 }),
      ),
    );
    render(<RegisterForm next="/" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "long enough passphrase" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "long enough passphrase" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    const message = await screen.findByText("An account with this email already exists.");
    expect(screen.getByLabelText("Email").getAttribute("aria-describedby")).toBe(message.id);
  });
});

describe("LoginForm", () => {
  it("shows the server's error and the expired-session notice", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/auth/csrf")
          ? Response.json({ csrf_token: "t" })
          : Response.json({ error: { code: "invalid_credentials", message: "Incorrect email or password." } }, { status: 401 }),
      ),
    );
    render(<LoginForm next="/" reason="expired" />);
    expect(screen.getByText("Your session has expired. Please sign in again.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "wrong password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Incorrect email or password."));
  });

  it("toggles password visibility without changing the value", () => {
    render(<LoginForm next="/" />);
    const input = screen.getByLabelText("Password", { exact: true }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  spaces kept  " } });
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input.type).toBe("text");
    expect(input.value).toBe("  spaces kept  ");
  });
});
