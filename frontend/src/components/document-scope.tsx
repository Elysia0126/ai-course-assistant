"use client";

import { Check, ChevronDown, Files } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/format";
import type { CourseDocument } from "@/lib/types";

import { FileIcon } from "./file-icon";

/** Choose which documents a question/quiz/deck should draw from. An empty selection means "all". */
export function DocumentScope({
  documents,
  value,
  onChange,
  align = "left",
  placement = "down",
}: {
  documents: CourseDocument[];
  value: string[];
  onChange: (ids: string[]) => void;
  align?: "left" | "right";
  placement?: "down" | "up";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const label =
    value.length === 0
      ? "All materials"
      : value.length === 1
        ? (documents.find((d) => d.id === value[0])?.filename ?? "1 document")
        : `${value.length} documents`;

  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex max-w-64 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 shadow-xs hover:bg-slate-50"
      >
        <Files className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0" />
      </button>
      {open && (
        <div
          className={cn(
            "absolute z-40 max-h-72 w-80 overflow-y-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl",
            align === "right" ? "right-0" : "left-0",
            placement === "up" ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          <button
            type="button"
            onClick={() => onChange([])}
            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-sm hover:bg-slate-50"
          >
            <span className="font-medium text-slate-800">All materials</span>
            {value.length === 0 && <Check className="h-4 w-4 text-indigo-600" />}
          </button>
          <div className="my-1 h-px bg-slate-100" />
          {documents.length === 0 && <p className="px-2.5 py-2 text-sm text-slate-500">No processed documents yet.</p>}
          {documents.map((doc) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => toggle(doc.id)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-50"
            >
              <FileIcon type={doc.file_type} className="h-7 w-7" />
              <span className="min-w-0 flex-1 truncate text-slate-700">{doc.filename}</span>
              {value.includes(doc.id) && <Check className="h-4 w-4 shrink-0 text-indigo-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
