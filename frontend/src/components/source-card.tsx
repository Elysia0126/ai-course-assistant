import { ExternalLink } from "lucide-react";

import { api } from "@/lib/api";
import { cn, sourceLabel } from "@/lib/format";
import type { SourceRef } from "@/lib/types";

import { FileIcon } from "./file-icon";

type SourceLike = Pick<SourceRef, "document_id" | "filename" | "file_type" | "page_number" | "section" | "snippet"> & {
  index?: number | null;
};

/** A citation target: file, exact page/slide, the retrieved snippet, and a deep link to the original. */
export function SourceCard({ source, id, compact }: { source: SourceLike; id?: string; compact?: boolean }) {
  const href = api.documents.fileUrl(source.document_id, source.file_type === "pdf" ? source.page_number : null);
  return (
    <div id={id} className={cn("rounded-xl border border-slate-200 bg-white p-3 transition", compact && "p-2.5")}>
      <div className="flex items-center gap-2.5">
        {source.index != null ? (
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-indigo-100 text-xs font-semibold text-indigo-700">
            {source.index}
          </span>
        ) : (
          <FileIcon type={source.file_type} className="h-6 w-6 [&_svg]:h-3.5 [&_svg]:w-3.5" />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-slate-800">{source.filename}</p>
          <p className="truncate text-[11px] text-slate-500">
            {sourceLabel(source)}
            {source.section && source.page_number != null ? ` · ${source.section}` : ""}
          </p>
        </div>
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50"
          title={source.file_type === "pdf" && source.page_number ? `Open page ${source.page_number}` : "Open file"}
        >
          Open <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {!compact && <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-600">{source.snippet}</p>}
    </div>
  );
}
