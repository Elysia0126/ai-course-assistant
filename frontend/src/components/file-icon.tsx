import { FileText, FileType2, Presentation, ScrollText } from "lucide-react";

import { cn } from "@/lib/format";

const STYLES: Record<string, { icon: typeof FileText; className: string }> = {
  pdf: { icon: FileText, className: "bg-rose-50 text-rose-600" },
  pptx: { icon: Presentation, className: "bg-amber-50 text-amber-600" },
  docx: { icon: FileType2, className: "bg-blue-50 text-blue-600" },
  md: { icon: ScrollText, className: "bg-emerald-50 text-emerald-600" },
  txt: { icon: ScrollText, className: "bg-slate-100 text-slate-600" },
};

export function FileIcon({ type, className }: { type: string; className?: string }) {
  const style = STYLES[type] ?? STYLES.txt;
  const Icon = style.icon;
  return (
    <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", style.className, className)}>
      <Icon className="h-4.5 w-4.5" />
    </span>
  );
}
