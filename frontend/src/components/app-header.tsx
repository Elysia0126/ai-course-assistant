"use client";

import { BookOpenCheck, Cpu, LogOut, Shield, WifiOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useOptionalAuth } from "@/components/auth-context";
import { api } from "@/lib/api";
import { displayName } from "@/lib/auth";
import { cn, providerLabel } from "@/lib/format";
import type { Health } from "@/lib/types";

export function AppHeader() {
  const auth = useOptionalAuth();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setOffline(true));
  }, []);

  const providerTone =
    health?.llm.provider === "offline" ? "bg-amber-50 text-amber-800 ring-amber-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200";

  async function signOut() {
    if (!auth) return;
    setSigningOut(true);
    await auth.logout();
  }

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm">
            <BookOpenCheck className="h-4.5 w-4.5" />
          </span>
          <span className="truncate font-semibold tracking-tight text-slate-900">
            Course<span className="text-indigo-600">Assistant</span>
          </span>
        </Link>
        <div className="flex min-w-0 items-center gap-2 text-xs">
          {offline && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 font-medium text-rose-700 ring-1 ring-rose-200">
              <WifiOff className="h-3.5 w-3.5" /> <span className="hidden sm:inline">API unreachable</span>
            </span>
          )}
          {health && (
            <>
              <span
                className={cn("hidden items-center gap-1.5 rounded-full px-2.5 py-1 font-medium ring-1 sm:inline-flex", providerTone)}
                title={
                  health.llm.provider === "offline"
                    ? "No LLM API key configured — answers are extracted from your materials. Set ANTHROPIC_API_KEY to enable generation."
                    : `LLM: ${health.llm.provider} / ${health.llm.model}`
                }
              >
                <Cpu className="h-3.5 w-3.5" />
                {providerLabel(health.llm.provider, health.llm.model)}
              </span>
              <span
                className="hidden items-center rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600 ring-1 ring-slate-200 lg:inline-flex"
                title={`Embeddings: ${health.embeddings.model} (${health.embeddings.dim}-d)`}
              >
                {health.vector_store === "pgvector" ? "pgvector" : "in-process index"} · {health.embeddings.model.split("/").pop()}
              </span>
            </>
          )}
          {auth ? (
            <div className="flex min-w-0 items-center gap-1.5 border-l border-slate-200 pl-2 sm:pl-3">
              {auth.user.role === "admin" && (
                <Link
                  href="/admin"
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                >
                  <Shield className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Admin</span>
                </Link>
              )}
              <span className="flex min-w-0 items-center gap-2" title={auth.user.email}>
                <span
                  aria-hidden
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[13px] font-semibold text-indigo-700"
                >
                  {displayName(auth.user).charAt(0).toUpperCase()}
                </span>
                <span className="hidden max-w-36 truncate text-sm font-medium text-slate-700 md:inline" data-testid="current-user">
                  {displayName(auth.user)}
                </span>
              </span>
              <button
                type="button"
                onClick={signOut}
                disabled={signingOut}
                aria-label="Sign out"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50"
              >
                <LogOut className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Sign out</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1 border-l border-slate-200 pl-2 sm:pl-3">
              <Link href="/login" className="rounded-md px-2.5 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900">
                Sign in
              </Link>
              <Link href="/register" className="rounded-md bg-indigo-600 px-2.5 py-1.5 text-sm font-medium text-white hover:bg-indigo-500">
                Sign up
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
