"use client";

import {
  AlertTriangle,
  ArrowUp,
  ChevronDown,
  MessageSquarePlus,
  MessageSquareText,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";
import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useCourse } from "@/components/course-context";
import { DocumentScope } from "@/components/document-scope";
import { Markdown } from "@/components/markdown";
import { SourceCard } from "@/components/source-card";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn, providerLabel, timeAgo } from "@/lib/format";
import type { ChatMessage, ChatSessionSummary, SourceRef } from "@/lib/types";

interface UIMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceRef[];
  meta?: ChatMessage["meta"];
  lowConfidence?: boolean;
  status?: "searching" | "streaming" | "done" | "error" | "stopped";
  error?: string;
}

const SUGGESTIONS = [
  "Summarize the most important ideas in these materials.",
  "What key definitions should I memorize for the exam?",
  "Explain the hardest concept here with a simple example.",
];

let tempCounter = 0;
/** Client-side ids for optimistic messages until the server assigns real ones. */
const tempId = (prefix: string) => `${prefix}-${++tempCounter}`;

const toUI = (m: ChatMessage): UIMessage => ({
  id: m.id,
  role: m.role,
  content: m.content,
  sources: m.sources,
  meta: m.meta,
  lowConfidence: m.meta?.low_confidence,
  status: "done",
});

export default function AskPage() {
  const { course, readyDocuments, refreshCourse } = useCourse();
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [input, setInput] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const loadSessions = useCallback(() => {
    api.chat
      .sessions(course.id)
      .then(setSessions)
      .catch(() => undefined);
  }, [course.id]);

  useEffect(loadSessions, [loadSessions]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: busy ? "auto" : "smooth" });
  }, [messages, busy]);

  async function openSession(id: string) {
    if (busy) return;
    setSessionId(id);
    setLoadingSession(true);
    try {
      const detail = await api.chat.session(id);
      setMessages(detail.messages.map(toUI));
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setLoadingSession(false);
    }
  }

  function newChat() {
    if (busy) return;
    setSessionId(null);
    setMessages([]);
    textareaRef.current?.focus();
  }

  async function deleteSession(id: string) {
    try {
      await api.chat.remove(id);
      if (id === sessionId) newChat();
      loadSessions();
      refreshCourse();
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  function patchAssistant(id: string, patch: Partial<UIMessage> | ((m: UIMessage) => Partial<UIMessage>)) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)));
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setInput("");
    const assistantId = tempId("pending");
    setMessages((prev) => [
      ...prev,
      { id: tempId("user"), role: "user", content: question, sources: [] },
      { id: assistantId, role: "assistant", content: "", sources: [], status: "searching" },
    ]);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const isNew = !sessionId;
    let finalId = assistantId;

    try {
      await api.chat.stream(
        course.id,
        { question, session_id: sessionId, document_ids: scope.length ? scope : null },
        {
          onMeta: (meta) => setSessionId(meta.session_id),
          onSources: ({ sources, low_confidence }) =>
            patchAssistant(assistantId, { sources, lowConfidence: low_confidence, status: "streaming" }),
          onToken: (token) => patchAssistant(assistantId, (m) => ({ content: m.content + token })),
          onDone: (done) => {
            finalId = done.message_id;
            patchAssistant(assistantId, (m) => ({
              id: done.message_id,
              content: done.content,
              meta: done.meta,
              status: "done",
              sources: m.sources.map((s) => ({ ...s, cited: done.cited.includes(s.index ?? -1) })),
            }));
          },
        },
        controller.signal,
      );
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        patchAssistant(finalId, { status: "stopped" });
      } else {
        patchAssistant(finalId, { status: "error", error: errorMessage(error) });
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
      loadSessions();
      if (isNew) refreshCourse();
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(input);
    }
  }

  const noMaterials = readyDocuments.length === 0;

  return (
    <div className="grid h-[calc(100dvh-14rem)] min-h-[540px] gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="hidden flex-col overflow-hidden lg:flex">
        <div className="border-b border-slate-100 p-3">
          <Button variant="outline" className="w-full" icon={<MessageSquarePlus className="h-4 w-4" />} onClick={newChat}>
            New chat
          </Button>
        </div>
        <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {sessions.length === 0 && <p className="px-2 py-3 text-xs text-slate-500">Your conversations will appear here.</p>}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg pr-1 transition",
                s.id === sessionId ? "bg-indigo-50" : "hover:bg-slate-50",
              )}
            >
              <button onClick={() => openSession(s.id)} className="min-w-0 flex-1 px-2.5 py-2 text-left">
                <p className={cn("truncate text-sm", s.id === sessionId ? "font-medium text-indigo-800" : "text-slate-700")}>
                  {s.title}
                </p>
                <p className="text-[11px] text-slate-400">
                  {timeAgo(s.updated_at)} · {s.message_count} msgs
                </p>
              </button>
              <button
                onClick={() => deleteSession(s.id)}
                className="rounded-md p-1 text-slate-300 opacity-0 transition group-hover:opacity-100 hover:text-rose-600"
                aria-label="Delete chat"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="flex min-h-0 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          {loadingSession ? (
            <div className="flex h-full items-center justify-center">
              <Spinner className="h-6 w-6" />
            </div>
          ) : messages.length === 0 ? (
            <EmptyState
              className="h-full"
              icon={<MessageSquareText className="h-6 w-6" />}
              title={noMaterials ? "Upload materials to start asking" : `Ask anything about ${course.name}`}
              description={
                noMaterials
                  ? "Answers are grounded in your uploaded slides and notes, so add some materials first."
                  : "Answers cite the exact page or slide they come from. Click a citation to see the source."
              }
              action={
                !noMaterials && (
                  <div className="flex flex-col gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-left text-sm text-slate-700 shadow-xs transition hover:border-indigo-300 hover:bg-indigo-50/40"
                      >
                        <Sparkles className="h-4 w-4 shrink-0 text-indigo-500" /> {s}
                      </button>
                    ))}
                  </div>
                )
              }
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-6">
              {messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} text={m.content} /> : <AssistantMessage key={m.id} message={m} />))}
            </div>
          )}
        </div>

        <div className="rounded-b-2xl border-t border-slate-100 bg-white px-4 py-3 sm:px-8">
          <div className="mx-auto max-w-3xl">
            <div className="rounded-2xl border border-slate-200 bg-white shadow-xs focus-within:border-indigo-300 focus-within:ring-3 focus-within:ring-indigo-100">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={2}
                maxLength={4000}
                disabled={noMaterials}
                placeholder={noMaterials ? "Upload materials first…" : "Ask a question about your course… (Enter to send, Shift+Enter for a new line)"}
                className="block max-h-40 w-full resize-none rounded-2xl bg-transparent px-4 pt-3 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
              />
              <div className="flex items-center justify-between px-3 pb-2.5">
                <DocumentScope documents={readyDocuments} value={scope} onChange={setScope} placement="up" />
                {busy ? (
                  <Button size="sm" variant="secondary" icon={<Square className="h-3 w-3 fill-current" />} onClick={() => abortRef.current?.abort()}>
                    Stop
                  </Button>
                ) : (
                  <Button size="icon" className="h-8 w-8 rounded-full" disabled={!input.trim() || noMaterials} onClick={() => send(input)} aria-label="Send">
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm whitespace-pre-wrap text-white shadow-sm">{text}</div>
    </div>
  );
}

function AssistantMessage({ message }: { message: UIMessage }) {
  const [showAll, setShowAll] = useState(false);
  const cited = message.sources.filter((s) => s.cited);
  const others = message.sources.filter((s) => !s.cited);
  const done = message.status === "done" || message.status === "stopped" || message.status === "error";
  const visible = done && cited.length ? cited : message.sources;

  function focusSource(n: number) {
    if (!cited.some((s) => s.index === n)) setShowAll(true);
    requestAnimationFrame(() => {
      const el = document.getElementById(`src-${message.id}-${n}`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      el.classList.remove("source-highlight");
      void el.offsetWidth;
      el.classList.add("source-highlight");
    });
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
        <Sparkles className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {message.lowConfidence && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            The retrieved passages are only weakly related to this question — the course materials may not cover it.
          </div>
        )}

        {message.status === "searching" && <Thinking label="Searching your materials…" />}
        {message.status === "streaming" && !message.content && <Thinking label="Writing an answer…" />}
        {message.content && (
          <Markdown content={message.content} sourceCount={message.sources.length} onCite={focusSource} />
        )}
        {message.status === "streaming" && message.content && <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-indigo-400" />}
        {message.status === "error" && (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{message.error}</p>
        )}
        {message.status === "stopped" && <p className="text-xs text-slate-400">Generation stopped.</p>}

        {message.sources.length > 0 && (
          <div>
            <p className="mb-2 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">
              {done && cited.length ? "Cited sources" : "Retrieved sources"}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(showAll ? [...visible, ...(done && cited.length ? others : [])] : visible).map((s) => (
                <SourceCard key={`${s.chunk_id}-${s.index}`} id={`src-${message.id}-${s.index}`} source={s} />
              ))}
            </div>
            {done && cited.length > 0 && others.length > 0 && (
              <button
                onClick={() => setShowAll((v) => !v)}
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
              >
                <ChevronDown className={cn("h-3.5 w-3.5 transition", showAll && "rotate-180")} />
                {showAll ? "Hide" : "Show"} {others.length} more retrieved passage{others.length > 1 ? "s" : ""}
              </button>
            )}
          </div>
        )}

        {message.meta?.provider && done && (
          <p className="text-[11px] text-slate-400">
            {providerLabel(message.meta.provider, message.meta.model ?? "")}
            {message.meta.latency_ms != null && ` · ${(message.meta.latency_ms / 1000).toFixed(1)}s`}
          </p>
        )}
      </div>
    </div>
  );
}

function Thinking({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="flex gap-1">
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-indigo-400" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-indigo-400" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-indigo-400" />
      </span>
      {label}
    </div>
  );
}
