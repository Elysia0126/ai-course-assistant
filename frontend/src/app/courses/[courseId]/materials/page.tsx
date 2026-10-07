"use client";

import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Eye,
  FileSearch,
  Loader2,
  RotateCcw,
  Search,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { type DragEvent, type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useCourse } from "@/components/course-context";
import { FileIcon } from "@/components/file-icon";
import { Badge, Button, Card, EmptyState, Input, Modal, ProgressBar, Segmented, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn, formatBytes, sourceLabel, timeAgo } from "@/lib/format";
import type { Chunk, CourseDocument, SearchMode, SearchResponse } from "@/lib/types";

const ACCEPT = ".pdf,.pptx,.docx,.md,.markdown,.txt";

export default function MaterialsPage() {
  const { course, documents, refreshDocuments, refreshCourse } = useCourse();
  const [inspecting, setInspecting] = useState<CourseDocument | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const stale = documents.filter((d) => d.needs_reindex).length;

  async function reindexAll() {
    setReindexing(true);
    try {
      await api.courses.reindex(course.id);
      toast.success("Re-indexing all materials…");
      await refreshDocuments();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setReindexing(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-6">
        {stale > 0 && (
          <div className="flex flex-col gap-3 rounded-2xl bg-amber-50 px-5 py-4 text-sm text-amber-900 ring-1 ring-amber-200 sm:flex-row sm:items-center">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <p className="flex-1">
              {stale} document{stale > 1 ? "s were" : " was"} indexed with a different embedding model than the one now
              configured. Search is paused for them until they are re-indexed.
            </p>
            <Button size="sm" variant="secondary" loading={reindexing} onClick={reindexAll} icon={<RotateCcw className="h-3.5 w-3.5" />}>
              Re-index all
            </Button>
          </div>
        )}
        <UploadZone
          courseId={course.id}
          onUploaded={async () => {
            await refreshDocuments();
            await refreshCourse();
          }}
        />
        <Card>
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-900">Course materials</h2>
            <span className="text-xs text-slate-500">{documents.length} files</span>
          </div>
          {documents.length === 0 ? (
            <EmptyState
              icon={<UploadCloud className="h-6 w-6" />}
              title="No materials yet"
              description="Upload lecture slides (PPTX), PDFs, Word documents or Markdown notes. They're parsed page by page so answers can cite exact locations."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  onInspect={() => setInspecting(doc)}
                  onChanged={async () => {
                    await refreshDocuments();
                    await refreshCourse();
                  }}
                />
              ))}
            </ul>
          )}
        </Card>
      </div>
      <RetrievalPlayground courseId={course.id} disabled={course.stats.ready_document_count === 0} />
      {inspecting && <ChunkInspector doc={inspecting} onClose={() => setInspecting(null)} />}
    </div>
  );
}

function UploadZone({ courseId, onUploaded }: { courseId: string; onUploaded: () => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);

  async function upload(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    if (!files.length) return;
    setProgress(0);
    try {
      const result = await api.documents.upload(courseId, files, setProgress);
      if (result.documents.length) {
        toast.success(`Uploaded ${result.documents.length} file${result.documents.length > 1 ? "s" : ""} — indexing…`);
      }
      result.errors.forEach((e) => toast.error(e.message));
      await onUploaded();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setProgress(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    upload(event.dataTransfer.files);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => progress === null && inputRef.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-9 text-center transition",
        dragging ? "border-indigo-400 bg-indigo-50/60" : "border-slate-200 bg-white hover:border-indigo-300 hover:bg-slate-50/60",
      )}
    >
      <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => e.target.files && upload(e.target.files)} />
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
        {progress === null ? <UploadCloud className="h-5.5 w-5.5" /> : <Loader2 className="h-5.5 w-5.5 animate-spin" />}
      </div>
      {progress === null ? (
        <>
          <p className="text-sm font-medium text-slate-800">
            Drop files here or <span className="text-indigo-600">browse</span>
          </p>
          <p className="mt-1 text-xs text-slate-500">PDF, PowerPoint (.pptx), Word (.docx), Markdown or text · up to 25 MB each</p>
        </>
      ) : (
        <div className="w-64">
          <p className="mb-2 text-sm font-medium text-slate-800">Uploading… {Math.round(progress * 100)}%</p>
          <ProgressBar value={progress} />
        </div>
      )}
    </div>
  );
}

function StatusBadge({ doc }: { doc: CourseDocument }) {
  if (doc.status === "ready")
    return (
      <Badge tone="emerald">
        <CheckCircle2 className="h-3 w-3" /> Ready
      </Badge>
    );
  if (doc.status === "failed")
    return (
      <Badge tone="rose" title={doc.error_message ?? undefined}>
        <AlertCircle className="h-3 w-3" /> Failed
      </Badge>
    );
  return (
    <Badge tone="sky">
      <Loader2 className="h-3 w-3 animate-spin" /> {doc.status === "pending" ? "Queued" : "Indexing"}
    </Badge>
  );
}

function DocumentRow({ doc, onInspect, onChanged }: { doc: CourseDocument; onInspect: () => void; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const unit = doc.file_type === "pptx" ? "slides" : "pages";

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      toast.success(success);
      await onChanged();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex items-center gap-3 px-5 py-3.5">
      <FileIcon type={doc.file_type} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <a
            href={api.documents.fileUrl(doc.id)}
            target="_blank"
            rel="noreferrer"
            className="truncate text-sm font-medium text-slate-900 hover:text-indigo-600"
          >
            {doc.filename}
          </a>
          <StatusBadge doc={doc} />
        </div>
        <p className={cn("mt-0.5 truncate text-xs", doc.status === "failed" ? "text-rose-600" : "text-slate-500")}>
          {doc.status === "failed"
            ? doc.error_message
            : [
                formatBytes(doc.size_bytes),
                doc.page_count ? `${doc.page_count} ${unit}` : null,
                doc.status === "ready" ? `${doc.chunk_count} chunks` : null,
                `added ${timeAgo(doc.created_at)}`,
              ]
                .filter(Boolean)
                .join(" · ")}
        </p>
      </div>
      <div className="flex items-center gap-0.5">
        {doc.status === "ready" && (
          <Button variant="ghost" size="icon" onClick={onInspect} title="Inspect chunks" aria-label="Inspect chunks">
            <Eye className="h-4 w-4" />
          </Button>
        )}
        {doc.status === "failed" && (
          <Button
            variant="ghost"
            size="icon"
            disabled={busy}
            onClick={() => run(() => api.documents.reprocess(doc.id), "Re-processing started")}
            title="Retry"
            aria-label="Retry processing"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          disabled={busy}
          onClick={() => window.confirm(`Delete ${doc.filename}?`) && run(() => api.documents.remove(doc.id), "Document deleted")}
          title="Delete"
          aria-label="Delete document"
          className="hover:text-rose-600"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </li>
  );
}

function ChunkInspector({ doc, onClose }: { doc: CourseDocument; onClose: () => void }) {
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  useEffect(() => {
    api.documents
      .chunks(doc.id)
      .then(setChunks)
      .catch((e) => toast.error(errorMessage(e)));
  }, [doc.id]);

  return (
    <Modal open onClose={onClose} wide title={doc.filename} description={`${doc.chunk_count} chunks — exactly what the retriever searches over.`}>
      {!chunks ? (
        <div className="flex justify-center py-10">
          <Spinner className="h-6 w-6" />
        </div>
      ) : (
        <ol className="space-y-3">
          {chunks.map((chunk) => (
            <li key={chunk.id} className="rounded-xl border border-slate-200 p-3.5">
              <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <Badge tone="indigo">#{chunk.chunk_index + 1}</Badge>
                <span className="font-medium text-slate-700">{sourceLabel({ ...chunk, file_type: doc.file_type })}</span>
                {chunk.section && chunk.page_number != null && <span className="truncate">· {chunk.section}</span>}
                <span className="ml-auto">{chunk.char_count} chars</span>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{chunk.content}</p>
            </li>
          ))}
        </ol>
      )}
    </Modal>
  );
}

function RetrievalPlayground({ courseId, disabled }: { courseId: string; disabled: boolean }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);

  async function run(nextMode: SearchMode) {
    if (!query.trim()) return;
    setLoading(true);
    try {
      setResult(await api.search(courseId, query, nextMode));
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  function search(event: FormEvent) {
    event.preventDefault();
    run(mode);
  }

  function changeMode(next: SearchMode) {
    setMode(next);
    if (result) run(next); // compare retrievers on the same query
  }

  return (
    <Card className="h-fit lg:sticky lg:top-20">
      <div className="border-b border-slate-100 px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <FileSearch className="h-4 w-4 text-indigo-600" /> Retrieval inspector
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Dense vectors + BM25 keyword ranking, fused with Reciprocal Rank Fusion. Switch retrievers to compare.
        </p>
        <div className="mt-3">
          <Segmented
            value={mode}
            onChange={changeMode}
            options={[
              { value: "hybrid", label: "Hybrid" },
              { value: "vector", label: "Vector" },
              { value: "keyword", label: "Keyword" },
            ]}
          />
        </div>
      </div>
      <form onSubmit={search} className="flex gap-2 px-5 pt-4">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. what is momentum?" disabled={disabled} />
        <Button type="submit" size="icon" loading={loading} disabled={disabled || !query.trim()} aria-label="Search">
          {!loading && <Search className="h-4 w-4" />}
        </Button>
      </form>
      <div className="max-h-[60vh] space-y-2.5 overflow-y-auto px-5 py-4">
        {disabled && <p className="text-sm text-slate-500">Upload and index materials to try retrieval.</p>}
        {result?.low_confidence && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Low semantic similarity (best {result.best_vector_score.toFixed(2)}) — the materials may not cover this.
          </p>
        )}
        {result?.results.map((hit) => (
          <div key={hit.chunk_id} className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate font-medium text-slate-800">
                {hit.index}. {hit.filename}
              </span>
              <span className="shrink-0 text-slate-500">{sourceLabel(hit)}</span>
            </div>
            <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-slate-600">{hit.snippet}</p>
            <div className="mt-2 flex gap-1.5">
              <Badge tone="indigo" title="Cosine similarity of embeddings">
                vec {hit.vector_score?.toFixed(2) ?? "—"}
              </Badge>
              <Badge tone="emerald" title="Keyword (full-text / BM25) score">
                kw {hit.keyword_score?.toFixed(2) ?? "—"}
              </Badge>
              <Badge title="Reciprocal Rank Fusion score">rrf {hit.score?.toFixed(3)}</Badge>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
