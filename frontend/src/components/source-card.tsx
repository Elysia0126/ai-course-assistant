"use client";

import { ExternalLink, Eye } from "lucide-react";
import { useEffect, useState } from "react";

import { api, errorMessage } from "@/lib/api";
import { cn, sourceLabel } from "@/lib/format";
import type { ChunkDetail, SourceRef } from "@/lib/types";

import { FileIcon } from "./file-icon";
import { Modal, Spinner } from "./ui";

type SourceLike = Pick<SourceRef, "document_id" | "filename" | "file_type" | "page_number" | "section" | "snippet"> & {
  index?: number | null;
  chunk_id?: string | null;
};

function originalUrl(source: SourceLike): string {
  return api.documents.fileUrl(source.document_id, source.file_type === "pdf" ? source.page_number : null);
}

/** A citation target: file, exact page/slide, the retrieved snippet, the full passage and a deep link. */
export function SourceCard({ source, id, compact }: { source: SourceLike; id?: string; compact?: boolean }) {
  const [viewing, setViewing] = useState(false);
  return (
    <div id={id} className={cn("min-w-0 rounded-xl border border-slate-200 bg-white p-3 transition", compact && "p-2.5")}>
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
        {source.chunk_id && (
          <button
            type="button"
            onClick={() => setViewing(true)}
            className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            title="Read the full indexed passage"
          >
            <Eye className="h-3 w-3" /> View
          </button>
        )}
        <a
          href={originalUrl(source)}
          target="_blank"
          rel="noreferrer"
          className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50"
          title={source.file_type === "pdf" && source.page_number ? `Open page ${source.page_number}` : "Open file"}
        >
          Open <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {!compact && <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-600">{source.snippet}</p>}
      {viewing && source.chunk_id && <PassageViewer chunkId={source.chunk_id} source={source} onClose={() => setViewing(false)} />}
    </div>
  );
}

/** Shows exactly what the retriever handed to the model — the basis for checking an answer. */
export function PassageViewer({ chunkId, source, onClose }: { chunkId: string; source: SourceLike; onClose: () => void }) {
  const [chunk, setChunk] = useState<ChunkDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .chunk(chunkId)
      .then((data) => !cancelled && setChunk(data))
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [chunkId]);

  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={source.filename}
      description={`${sourceLabel(source)}${source.section && source.page_number != null ? ` · ${source.section}` : ""} — the exact passage that was retrieved`}
      footer={
        <a
          href={originalUrl(source)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Open original <ExternalLink className="h-3.5 w-3.5" />
        </a>
      }
    >
      {!chunk && !error && (
        <div className="flex justify-center py-10">
          <Spinner className="h-6 w-6" />
        </div>
      )}
      {error && (
        <div className="space-y-3">
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{error}</p>
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-700">{source.snippet}</p>
        </div>
      )}
      {chunk && (
        <blockquote className="border-l-3 border-indigo-200 pl-4 text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
          {chunk.content}
        </blockquote>
      )}
    </Modal>
  );
}
