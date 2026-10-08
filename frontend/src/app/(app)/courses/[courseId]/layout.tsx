"use client";

import { ArrowLeft, FolderOpen, Layers, ListChecks, MessageSquareText, Pencil } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { CourseProvider, useCourse } from "@/components/course-context";
import { CourseFormDialog } from "@/components/course-form";
import { Button, Card, Spinner } from "@/components/ui";
import { COURSE_COLORS, cn } from "@/lib/format";

export default function CourseLayout({ children }: { children: ReactNode }) {
  const { courseId } = useParams<{ courseId: string }>();
  return (
    <CourseProvider
      courseId={courseId}
      fallback={
        <div className="flex flex-1 items-center justify-center py-24">
          <Spinner className="h-6 w-6" />
        </div>
      }
      renderError={(message) => (
        <div className="mx-auto max-w-lg px-4 py-24">
          <Card className="p-6 text-center">
            <p className="font-medium text-slate-900">Couldn&apos;t load this course</p>
            <p className="mt-1 text-sm text-slate-500">{message}</p>
            <Link href="/" className="mt-4 inline-block text-sm font-medium text-indigo-600 hover:underline">
              Back to courses
            </Link>
          </Card>
        </div>
      )}
    >
      <CourseShell>{children}</CourseShell>
    </CourseProvider>
  );
}

const TABS = [
  { slug: "materials", label: "Materials", icon: FolderOpen },
  { slug: "ask", label: "Ask", icon: MessageSquareText },
  { slug: "quiz", label: "Quiz", icon: ListChecks },
  { slug: "flashcards", label: "Flashcards", icon: Layers },
] as const;

function CourseShell({ children }: { children: ReactNode }) {
  const { course, setCourse } = useCourse();
  const pathname = usePathname();
  const [editing, setEditing] = useState(false);
  const color = COURSE_COLORS[course.color] ?? COURSE_COLORS.indigo;
  const counts: Record<string, number | undefined> = {
    materials: course.stats.ready_document_count,
    ask: course.stats.chat_count,
    quiz: course.stats.quiz_count,
    flashcards: course.stats.due_card_count || undefined,
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b border-slate-200/70 bg-white">
        <div className="mx-auto max-w-7xl px-4 pt-5 sm:px-6">
          <Link href="/" className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
            <ArrowLeft className="h-3.5 w-3.5" /> All courses
          </Link>
          <div className="mt-2 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2.5">
                <span className={cn("h-3 w-3 shrink-0 rounded-full", color.dot)} />
                <h1 className="truncate text-xl font-semibold tracking-tight text-slate-900">{course.name}</h1>
              </div>
              <p className="mt-0.5 pl-5.5 text-sm text-slate-500">
                {[course.code, course.term].filter(Boolean).join(" · ") || "Course"} · {course.stats.ready_document_count}{" "}
                materials · {course.stats.chunk_count} indexed chunks
              </p>
            </div>
            <Button variant="ghost" size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)}>
              Edit
            </Button>
          </div>
          <nav className="-mb-px mt-4 flex gap-1 overflow-x-auto">
            {TABS.map(({ slug, label, icon: Icon }) => {
              const active = pathname.endsWith(`/${slug}`);
              return (
                <Link
                  key={slug}
                  href={`/courses/${course.id}/${slug}`}
                  className={cn(
                    "flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition",
                    active ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                  {counts[slug] ? (
                    <span
                      className={cn(
                        "rounded-full px-1.5 text-[11px] tabular-nums",
                        slug === "flashcards" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600",
                      )}
                    >
                      {counts[slug]}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-6 sm:px-6">{children}</div>
      {editing && <CourseFormDialog open course={course} onClose={() => setEditing(false)} onSaved={setCourse} />}
    </div>
  );
}
