import { NextResponse, type NextRequest } from "next/server";

import { isPublicPath } from "@/lib/auth";
import { sessionCookieName } from "@/lib/server-config";

/**
 * Navigation helper only (Next.js 16 "proxy", formerly middleware). Visitors without any session cookie
 * are sent to /login before a private page renders, and the server layout learns which page was asked
 * for (to come back to it after signing in). It never grants access: a cookie being present proves
 * nothing — the (app) layout asks FastAPI, and FastAPI authorises every API call itself.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!isPublicPath(pathname) && !request.cookies.has(sessionCookieName())) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = new URLSearchParams({ next: `${pathname}${search}` }).toString();
    return NextResponse.redirect(login);
  }
  const headers = new Headers(request.headers);
  headers.set("x-aica-pathname", `${pathname}${search}`); // overwrites anything the client sent
  return NextResponse.next({ request: { headers } });
}

export const config = {
  // Pages only: not the API proxy, build assets or icons.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)"],
};
