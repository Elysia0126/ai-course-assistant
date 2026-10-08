/** Helpers shared by the sign-in pages, the server layout and the client. No secrets in here. */

/** Pages that don't need a session (everything else does). */
export const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"] as const;

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

const SENTINEL_ORIGIN = "http://internal.invalid";

/**
 * Where to go after signing in. Only same-site paths are allowed: absolute URLs, protocol-relative
 * ("//evil.com"), backslash tricks ("/\\evil.com"), control characters, API routes and the auth pages
 * themselves (which would loop) all fall back to "/".
 */
export function safeNextPath(value: string | null | undefined, fallback = "/"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return fallback;
  if (/[\u0000-\u001f\u007f]/.test(value)) return fallback;
  let url: URL;
  try {
    url = new URL(value, SENTINEL_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== SENTINEL_ORIGIN) return fallback;
  if (url.pathname === "/api" || url.pathname.startsWith("/api/") || isPublicPath(url.pathname)) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Mirrors the server policy for instant feedback; FastAPI re-checks everything (and is the authority). */
export const PASSWORD_MIN_LENGTH = 15;
export const PASSWORD_MAX_LENGTH = 128;

/** Length in characters as the server counts them (Unicode code points after NFKC), not UTF-16 units. */
export function passwordLength(password: string): number {
  return [...password.normalize("NFKC")].length;
}

export function checkNewPassword(password: string, confirm: string): { password?: string; password_confirm?: string } {
  const length = passwordLength(password);
  if (length < PASSWORD_MIN_LENGTH) return { password: `Use at least ${PASSWORD_MIN_LENGTH} characters (${length} so far).` };
  if (length > PASSWORD_MAX_LENGTH) return { password: `Use at most ${PASSWORD_MAX_LENGTH} characters.` };
  if (password !== confirm) return { password_confirm: "The passwords don't match." };
  return {};
}

export function displayName(user: { display_name: string | null; email: string }): string {
  return user.display_name?.trim() || user.email.split("@")[0];
}
