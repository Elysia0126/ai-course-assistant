import clsx, { type ClassValue } from "clsx";

import type { CourseColor } from "./types";

export const cn = (...inputs: ClassValue[]) => clsx(inputs);

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function sourceLabel(source: { file_type: string; page_number: number | null; section: string | null }): string {
  if (source.page_number != null) return source.file_type === "pptx" ? `Slide ${source.page_number}` : `Page ${source.page_number}`;
  return source.section ?? "Document";
}

export function providerLabel(provider: string, model: string): string {
  if (provider === "offline") return "Offline mode";
  if (provider === "anthropic") return `Claude · ${model.replace(/^claude-/, "")}`;
  return model;
}

/** Static class maps so Tailwind can see every class name at build time. */
export const COURSE_COLORS: Record<CourseColor, { bar: string; soft: string; text: string; dot: string; ring: string }> = {
  indigo: { bar: "bg-indigo-500", soft: "bg-indigo-50", text: "text-indigo-700", dot: "bg-indigo-500", ring: "ring-indigo-500" },
  blue: { bar: "bg-blue-500", soft: "bg-blue-50", text: "text-blue-700", dot: "bg-blue-500", ring: "ring-blue-500" },
  emerald: { bar: "bg-emerald-500", soft: "bg-emerald-50", text: "text-emerald-700", dot: "bg-emerald-500", ring: "ring-emerald-500" },
  amber: { bar: "bg-amber-500", soft: "bg-amber-50", text: "text-amber-700", dot: "bg-amber-500", ring: "ring-amber-500" },
  rose: { bar: "bg-rose-500", soft: "bg-rose-50", text: "text-rose-700", dot: "bg-rose-500", ring: "ring-rose-500" },
  violet: { bar: "bg-violet-500", soft: "bg-violet-50", text: "text-violet-700", dot: "bg-violet-500", ring: "ring-violet-500" },
  cyan: { bar: "bg-cyan-500", soft: "bg-cyan-50", text: "text-cyan-700", dot: "bg-cyan-500", ring: "ring-cyan-500" },
  slate: { bar: "bg-slate-500", soft: "bg-slate-100", text: "text-slate-700", dot: "bg-slate-500", ring: "ring-slate-500" },
};
