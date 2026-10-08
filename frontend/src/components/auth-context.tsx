"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef } from "react";

import { ApiError, api, onUnauthorized, resetClientSession } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** For components rendered both signed in and signed out (the header). */
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

/**
 * Holds the user the server layout verified with FastAPI. Leaving the session always uses a full page load,
 * so no course data, router cache or in-flight request of the previous user survives in this tab.
 */
export function AuthProvider({ user, children }: { user: User; children: ReactNode }) {
  const leaving = useRef(false);

  const leave = useCallback((destination: string) => {
    if (leaving.current) return;
    leaving.current = true;
    resetClientSession(); // cancel uploads, answer streams and everything else still running
    window.location.replace(destination);
  }, []);

  const toLogin = useCallback(() => {
    const next = `${window.location.pathname}${window.location.search}`;
    leave(`/login?${new URLSearchParams({ next, reason: "expired" })}`);
  }, [leave]);

  // Any private request answered with 401 (session expired, revoked, account disabled).
  useEffect(() => onUnauthorized(toLogin), [toLogin]);

  // Another tab may have signed out or switched accounts: re-check whenever this one becomes visible.
  useEffect(() => {
    const recheck = () => {
      if (document.visibilityState !== "visible" || leaving.current) return;
      api.auth
        .me()
        .then((me) => {
          if (me.id !== user.id) leave(window.location.pathname); // different account now: reload as them
        })
        .catch((error) => {
          if (error instanceof ApiError && error.status === 401) toLogin();
        });
    };
    document.addEventListener("visibilitychange", recheck);
    return () => document.removeEventListener("visibilitychange", recheck);
  }, [user.id, leave, toLogin]);

  const logout = useCallback(async () => {
    leaving.current = true;
    try {
      await api.auth.logout();
    } finally {
      leaving.current = false;
      leave("/login?reason=signed-out");
    }
  }, [leave]);

  const value = useMemo(() => ({ user, logout }), [user, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
