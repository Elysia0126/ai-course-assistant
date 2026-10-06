"use client";

import { BookOpen, Brain, FileText, Layers, ListChecks, MessageSquareText, Plus, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { CourseFormDialog } from "@/components/course-form";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { COURSE_COLORS, cn, timeAgo } from "@/lib/format";
import type { Course } from "@/lib/types";

export default function DashboardPage() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api.courses
      .list()
      .then((data) => {
        setCourses(data);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  useEffect(load, [load]);

  async function remove(course: Course) {
    if (!window.confirm(`Delete "${course.name}" and all of its materials, chats, quizzes and flashcards?`)) return;
    try {
      await api.courses.remove(course.id);
      toast.success("Course deleted");
      load();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  const totals = (courses ?? []).reduce(
    (acc, c) => ({
      docs: acc.docs + c.stats.ready_document_count,
      due: acc.due + c.stats.due_card_count,
      quizzes: acc.quizzes + c.stats.quiz_count,
    }),
    { docs: 0, due: 0, quizzes: 0 },
  );

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
      <section className="mb-8 flex flex-col gap-6 rounded-3xl bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-600 px-7 py-8 text-white shadow-lg sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-xl">
          <p className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium">
            <Sparkles className="h-3.5 w-3.5" /> Grounded in your own course materials
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Study smarter with your lecture notes</h1>
          <p className="mt-2 text-sm text-indigo-100">
            Upload slides, PDFs and notes. Ask questions with page-level citations, generate quizzes, and review
            flashcards on a spaced-repetition schedule.
          </p>
        </div>
        <div className="flex gap-6 text-sm">
          <Stat label="Materials indexed" value={totals.docs} />
          <Stat label="Cards due" value={totals.due} />
          <Stat label="Quizzes" value={totals.quizzes} />
        </div>
      </section>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Your courses</h2>
        <Button onClick={() => setCreating(true)} icon={<Plus className="h-4 w-4" />}>
          New course
        </Button>
      </div>

      {error && (
        <Card className="border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {error}{" "}
          <button className="font-medium underline" onClick={load}>
            Retry
          </button>
        </Card>
      )}

      {!courses && !error && (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {courses && courses.length === 0 && (
        <Card>
          <EmptyState
            icon={<BookOpen className="h-6 w-6" />}
            title="Create your first course"
            description="A course groups lecture slides, PDFs and notes. Everything you ask or practise is grounded in what you upload."
            action={
              <Button onClick={() => setCreating(true)} icon={<Plus className="h-4 w-4" />}>
                New course
              </Button>
            }
          />
        </Card>
      )}

      {courses && courses.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <CourseCard key={course.id} course={course} onDelete={() => remove(course)} />
          ))}
        </div>
      )}

      {creating && <CourseFormDialog open onClose={() => setCreating(false)} onSaved={load} />}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-indigo-100">{label}</div>
    </div>
  );
}

function CourseCard({ course, onDelete }: { course: Course; onDelete: () => void }) {
  const color = COURSE_COLORS[course.color] ?? COURSE_COLORS.indigo;
  const s = course.stats;
  return (
    <Card className="group relative overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md">
      <div className={cn("h-1.5", color.bar)} />
      <Link href={`/courses/${course.id}/materials`} className="block p-5">
        <div className="mb-1 flex items-center gap-2 text-xs font-medium text-slate-500">
          {course.code && <span className={cn("rounded-md px-1.5 py-0.5", color.soft, color.text)}>{course.code}</span>}
          {course.term && <span>{course.term}</span>}
        </div>
        <h3 className="line-clamp-1 text-base font-semibold text-slate-900">{course.name}</h3>
        <p className="mt-1 line-clamp-2 min-h-10 text-sm text-slate-500">
          {course.description || "No description yet."}
        </p>
        <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs text-slate-500">
          <Metric icon={<FileText className="h-3.5 w-3.5" />} value={s.ready_document_count} label="files" />
          <Metric icon={<MessageSquareText className="h-3.5 w-3.5" />} value={s.chat_count} label="chats" />
          <Metric icon={<ListChecks className="h-3.5 w-3.5" />} value={s.quiz_count} label="quizzes" />
          <Metric icon={<Layers className="h-3.5 w-3.5" />} value={s.deck_count} label="decks" />
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
          <span>Updated {timeAgo(course.updated_at)}</span>
          {s.due_card_count > 0 ? (
            <Badge tone="amber">
              <Brain className="h-3 w-3" /> {s.due_card_count} cards due
            </Badge>
          ) : (
            <span>{s.chunk_count} chunks indexed</span>
          )}
        </div>
      </Link>
      <button
        onClick={onDelete}
        className="absolute top-4 right-3 rounded-md p-1.5 text-slate-300 opacity-0 transition group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600"
        aria-label={`Delete ${course.name}`}
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </Card>
  );
}

function Metric({ icon, value, label }: { icon: React.ReactNode; value: number; label: string }) {
  return (
    <div className="rounded-lg bg-slate-50 py-2">
      <div className="flex items-center justify-center gap-1 font-semibold text-slate-800">
        {icon}
        <span className="tabular-nums">{value}</span>
      </div>
      <div className="mt-0.5">{label}</div>
    </div>
  );
}
