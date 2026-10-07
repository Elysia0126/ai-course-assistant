"use client";

import {
  ArrowLeft,
  BookOpenCheck,
  Brain,
  Download,
  Eye,
  Layers,
  PartyPopper,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useCourse } from "@/components/course-context";
import { DocumentScope } from "@/components/document-scope";
import { Markdown } from "@/components/markdown";
import { SourceCard } from "@/components/source-card";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, ProgressBar, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { deckToAnkiText, downloadText, slugify } from "@/lib/export";
import { cn, timeAgo } from "@/lib/format";
import { formatInterval, nextIntervalDays } from "@/lib/srs";
import type { DeckDetail, DeckSummary, Flashcard, Rating } from "@/lib/types";

export default function FlashcardsPage() {
  const { course, refreshCourse } = useCourse();
  const [decks, setDecks] = useState<DeckSummary[] | null>(null);
  const [studying, setStudying] = useState<DeckSummary | null>(null);
  const [browsing, setBrowsing] = useState<DeckDetail | null>(null);

  const load = useCallback(() => {
    api.decks
      .list(course.id)
      .then(setDecks)
      .catch((e) => toast.error(errorMessage(e)));
  }, [course.id]);

  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      toast.success(message);
      load();
      refreshCourse();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (studying) {
    return (
      <StudySession
        deck={studying}
        onExit={() => {
          setStudying(null);
          load();
          refreshCourse();
        }}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
      <DeckGenerator
        onCreated={() => {
          load();
          refreshCourse();
        }}
      />
      <div>
        {!decks ? (
          <div className="flex justify-center py-14">
            <Spinner className="h-6 w-6" />
          </div>
        ) : decks.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Layers className="h-6 w-6" />}
              title="No flashcard decks yet"
              description="Generate a deck from your materials, then review it on an SM-2 spaced-repetition schedule."
            />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {decks.map((deck) => (
              <Card key={deck.id} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="line-clamp-2 text-sm font-semibold text-slate-900">{deck.title}</h3>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {deck.card_count} cards · {timeAgo(deck.created_at)}
                    </p>
                  </div>
                  {deck.due_count > 0 ? (
                    <Badge tone="amber">
                      <Brain className="h-3 w-3" /> {deck.due_count} due
                    </Badge>
                  ) : (
                    <Badge tone="emerald">Up to date</Badge>
                  )}
                </div>
                <div className="mt-4">
                  <div className="mb-1 flex justify-between text-[11px] text-slate-500">
                    <span>Reviewed</span>
                    <span className="tabular-nums">
                      {deck.reviewed_count}/{deck.card_count}
                    </span>
                  </div>
                  <ProgressBar value={deck.card_count ? deck.reviewed_count / deck.card_count : 0} />
                </div>
                <div className="mt-5 flex items-center gap-2">
                  <Button size="sm" className="flex-1" disabled={!deck.due_count} onClick={() => setStudying(deck)} icon={<BookOpenCheck className="h-4 w-4" />}>
                    {deck.due_count ? `Study ${deck.due_count}` : "Nothing due"}
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Browse cards"
                    aria-label="Browse cards"
                    onClick={() =>
                      api.decks
                        .get(deck.id)
                        .then(setBrowsing)
                        .catch((e) => toast.error(errorMessage(e)))
                    }
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Export for Anki (tab-separated text)"
                    aria-label="Export for Anki"
                    onClick={() =>
                      api.decks
                        .get(deck.id)
                        .then((full) => {
                          downloadText(`${slugify(full.title)}.txt`, deckToAnkiText(full.cards, slugify(course.code || course.name)));
                          toast.success("Exported — import the file in Anki via File → Import");
                        })
                        .catch((e) => toast.error(errorMessage(e)))
                    }
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Reset progress"
                    aria-label="Reset progress"
                    onClick={() => act(() => api.decks.reset(deck.id), "Progress reset — all cards are due")}
                  >
                    <RotateCcw className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Delete deck"
                    aria-label="Delete deck"
                    className="hover:text-rose-600"
                    onClick={() => window.confirm(`Delete "${deck.title}"?`) && act(() => api.decks.remove(deck.id), "Deck deleted")}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
      {browsing && (
        <Modal open wide onClose={() => setBrowsing(null)} title={browsing.title} description={`${browsing.cards.length} cards`}>
          <ol className="space-y-3">
            {browsing.cards.map((card, i) => (
              <li key={card.id} className="grid gap-3 rounded-xl border border-slate-200 p-4 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] font-semibold text-slate-400 uppercase">Front · {i + 1}</p>
                  <Markdown content={card.front} className="text-sm" />
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold text-slate-400 uppercase">Back</p>
                  <Markdown content={card.back} className="text-sm" />
                </div>
              </li>
            ))}
          </ol>
        </Modal>
      )}
    </div>
  );
}

function DeckGenerator({ onCreated }: { onCreated: () => void }) {
  const { course, readyDocuments } = useCourse();
  const [count, setCount] = useState(12);
  const [topic, setTopic] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  async function generate() {
    setLoading(true);
    try {
      const deck = await api.decks.generate(course.id, {
        num_cards: count,
        topic: topic || null,
        document_ids: scope.length ? scope : null,
      });
      toast.success(`Created “${deck.title}” with ${deck.card_count} cards`);
      onCreated();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="h-fit p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Sparkles className="h-4 w-4 text-indigo-600" /> Generate flashcards
      </h2>
      <p className="mt-1 text-xs text-slate-500">Atomic question → answer cards, each linked to its source page.</p>
      <div className="mt-5 space-y-5">
        <Field label={`Cards: ${count}`}>
          <input type="range" min={1} max={40} value={count} onChange={(e) => setCount(Number(e.target.value))} className="w-full accent-indigo-600" />
        </Field>
        <Field label="Focus topic" hint="Optional — leave empty to cover all selected materials.">
          <Input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200} placeholder="Any topic" />
        </Field>
        <div>
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Materials</span>
          <DocumentScope documents={readyDocuments} value={scope} onChange={setScope} />
        </div>
        <Button className="w-full" onClick={generate} loading={loading} disabled={!readyDocuments.length}>
          {loading ? "Creating cards…" : "Generate deck"}
        </Button>
      </div>
    </Card>
  );
}

const RATINGS: { rating: Rating; label: string; key: string; className: string }[] = [
  { rating: "again", label: "Again", key: "1", className: "bg-rose-50 text-rose-700 ring-rose-200 hover:bg-rose-100" },
  { rating: "hard", label: "Hard", key: "2", className: "bg-amber-50 text-amber-800 ring-amber-200 hover:bg-amber-100" },
  { rating: "good", label: "Good", key: "3", className: "bg-emerald-50 text-emerald-700 ring-emerald-200 hover:bg-emerald-100" },
  { rating: "easy", label: "Easy", key: "4", className: "bg-sky-50 text-sky-700 ring-sky-200 hover:bg-sky-100" },
];

function StudySession({ deck, onExit }: { deck: DeckSummary; onExit: () => void }) {
  const [queue, setQueue] = useState<Flashcard[] | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.decks
      .study(deck.id)
      .then((session) => setQueue(session.cards))
      .catch((e) => toast.error(errorMessage(e)));
  }, [deck.id]);

  const card = queue?.[index];

  const rate = useCallback(
    async (rating: Rating) => {
      if (!card || saving) return;
      setSaving(true);
      try {
        const updated = await api.decks.review(card.id, rating);
        setReviewed((r) => r + 1);
        setQueue((q) => {
          if (!q) return q;
          // "Again" puts the card back at the end of this session's queue.
          return rating === "again" ? [...q, updated] : q;
        });
        setIndex((i) => i + 1);
        setFlipped(false);
      } catch (e) {
        toast.error(errorMessage(e));
      } finally {
        setSaving(false);
      }
    },
    [card, saving],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!card) return;
      if (event.key === " ") {
        event.preventDefault();
        setFlipped((f) => !f);
      } else if (flipped) {
        const match = RATINGS.find((r) => r.key === event.key);
        if (match) rate(match.rating);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, flipped, rate]);

  const total = queue?.length ?? 0;

  return (
    <div className="mx-auto w-full max-w-2xl">
      <button onClick={onExit} className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> All decks
      </button>
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="truncate text-lg font-semibold text-slate-900">{deck.title}</h2>
        <span className="shrink-0 text-sm text-slate-500 tabular-nums">
          {Math.min(index + 1, total)} / {total}
        </span>
      </div>
      <ProgressBar value={total ? index / total : 0} className="mb-6" />

      {!queue ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6" />
        </div>
      ) : !card ? (
        <Card>
          <EmptyState
            icon={<PartyPopper className="h-6 w-6" />}
            title="Session complete!"
            description={`You reviewed ${reviewed} card${reviewed === 1 ? "" : "s"}. Each one is now scheduled for its next review.`}
            action={<Button onClick={onExit}>Back to decks</Button>}
          />
        </Card>
      ) : (
        <>
          <div className="flip-scene">
            <button
              type="button"
              onClick={() => setFlipped((f) => !f)}
              data-flipped={flipped}
              className="flip-card relative block h-80 w-full text-left"
              aria-label={flipped ? "Show question" : "Show answer"}
            >
              <div className="flip-face absolute inset-0 flex flex-col rounded-3xl border border-slate-200 bg-white p-8 shadow-lg">
                <p className="text-[11px] font-semibold tracking-wide text-indigo-500 uppercase">Question</p>
                <div className="flex flex-1 items-center justify-center text-center">
                  <Markdown content={card.front} className="text-lg font-medium text-slate-900" />
                </div>
                <p className="text-center text-xs text-slate-400">Click or press Space to reveal</p>
              </div>
              <div className="flip-face flip-back absolute inset-0 flex flex-col rounded-3xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-white p-8 shadow-lg">
                <p className="text-[11px] font-semibold tracking-wide text-indigo-500 uppercase">Answer</p>
                <div className="flex flex-1 items-center justify-center overflow-y-auto text-center">
                  <Markdown content={card.back} className="text-base text-slate-800" />
                </div>
              </div>
            </button>
          </div>

          <div className={cn("mt-6 grid grid-cols-4 gap-2 transition", !flipped && "pointer-events-none opacity-40")}>
            {RATINGS.map(({ rating, label, key, className }) => (
              <button
                key={rating}
                onClick={() => rate(rating)}
                disabled={!flipped || saving}
                className={cn("rounded-xl px-3 py-2.5 text-sm font-medium ring-1 transition", className)}
              >
                {label}
                <span className="block text-[11px] font-normal opacity-75">
                  {formatInterval(nextIntervalDays(card, rating))} · {key}
                </span>
              </button>
            ))}
          </div>
          {flipped && card.source && (
            <div className="mt-4">
              <SourceCard source={card.source} compact />
            </div>
          )}
        </>
      )}
    </div>
  );
}
