"use client";

import { BookOpenCheck, Cpu, WifiOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { cn, providerLabel } from "@/lib/format";
import type { Health } from "@/lib/types";

export function AppHeader() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setOffline(true));
  }, []);

  const providerTone =
    health?.llm.provider === "offline" ? "bg-amber-50 text-amber-800 ring-amber-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200";

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm">
            <BookOpenCheck className="h-4.5 w-4.5" />
          </span>
          <span className="font-semibold tracking-tight text-slate-900">
            Course<span className="text-indigo-600">Assistant</span>
          </span>
        </Link>
        <div className="flex items-center gap-2 text-xs">
          {offline && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 font-medium text-rose-700 ring-1 ring-rose-200">
              <WifiOff className="h-3.5 w-3.5" /> API unreachable
            </span>
          )}
          {health && (
            <>
              <span
                className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium ring-1", providerTone)}
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
                className="hidden items-center rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600 ring-1 ring-slate-200 md:inline-flex"
                title={`Embeddings: ${health.embeddings.model} (${health.embeddings.dim}-d)`}
              >
                {health.vector_store === "pgvector" ? "pgvector" : "in-process index"} · {health.embeddings.model.split("/").pop()}
              </span>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
