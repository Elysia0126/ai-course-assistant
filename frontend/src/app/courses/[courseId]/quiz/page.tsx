"use client";

import {
  ArrowLeft,
  CheckCircle2,
  ClipboardCheck,
  ListChecks,
  RotateCcw,
  Sparkles,
  Trash2,
  Trophy,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useCourse } from "@/components/course-context";
import { DocumentScope } from "@/components/document-scope";
import { Markdown } from "@/components/markdown";
import { SourceCard } from "@/components/source-card";
import { Badge, Button, Card, EmptyState, Field, Input, Segmented, Spinner, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn, timeAgo } from "@/lib/format";
import type { Difficulty, QuestionType, QuizAttempt, QuizDetail, QuizSummary } from "@/lib/types";

const TYPE_LABELS: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  true_false: "True / False",
  short_answer: "Short answer",
};

const DIFFICULTY_TONE: Record<Difficulty, "emerald" | "amber" | "rose"> = { easy: "emerald", medium: "amber", hard: "rose" };

export default function QuizPage() {
  const { course, refreshCourse } = useCourse();
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null);
  const [active, setActive] = useState<QuizDetail | null>(null);

  const load = useCallback(() => {
    api.quizzes
      .list(course.id)
      .then(setQuizzes)
      .catch((e) => toast.error(errorMessage(e)));
  }, [course.id]);

  useEffect(load, [load]);

  async function open(id: string) {
    try {
      setActive(await api.quizzes.get(id));
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function remove(quiz: QuizSummary) {
    if (!window.confirm(`Delete "${quiz.title}"?`)) return;
    try {
      await api.quizzes.remove(quiz.id);
      load();
      refreshCourse();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (active) {
    return (
      <QuizPlayer
        quiz={active}
        onExit={() => {
          setActive(null);
          load();
        }}
      />
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      <QuizGenerator
        onCreated={(quiz) => {
          setActive(quiz);
          refreshCourse();
        }}
      />
      <Card>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">Your quizzes</h2>
          <span className="text-xs text-slate-500">{quizzes?.length ?? 0} total</span>
        </div>
        {!quizzes ? (
          <div className="flex justify-center py-14">
            <Spinner className="h-6 w-6" />
          </div>
        ) : quizzes.length === 0 ? (
          <EmptyState
            icon={<ListChecks className="h-6 w-6" />}
            title="No quizzes yet"
            description="Generate a quiz from your materials. Every question links back to the page it was written from."
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {quizzes.map((quiz) => (
              <li key={quiz.id} className="group flex items-center gap-4 px-5 py-4">
                <button onClick={() => open(quiz.id)} className="min-w-0 flex-1 text-left">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-slate-900 group-hover:text-indigo-700">{quiz.title}</p>
                    <Badge tone={DIFFICULTY_TONE[quiz.difficulty]}>{quiz.difficulty}</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {quiz.question_count} questions · {quiz.attempt_count} attempt{quiz.attempt_count === 1 ? "" : "s"} ·{" "}
                    {timeAgo(quiz.created_at)}
                    {quiz.topic ? ` · topic: ${quiz.topic}` : ""}
                  </p>
                </button>
                {quiz.best_score != null && (
                  <div className="text-right">
                    <p className={cn("text-lg font-semibold tabular-nums", quiz.best_score >= 80 ? "text-emerald-600" : "text-slate-800")}>
                      {Math.round(quiz.best_score)}%
                    </p>
                    <p className="text-[11px] text-slate-400">best</p>
                  </div>
                )}
                <Button size="sm" variant="outline" onClick={() => open(quiz.id)}>
                  {quiz.attempt_count ? "Retake" : "Start"}
                </Button>
                <button
                  onClick={() => remove(quiz)}
                  className="rounded-md p-1.5 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
                  aria-label="Delete quiz"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function QuizGenerator({ onCreated }: { onCreated: (quiz: QuizDetail) => void }) {
  const { course, readyDocuments } = useCourse();
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [types, setTypes] = useState<QuestionType[]>(["mcq", "true_false", "short_answer"]);
  const [topic, setTopic] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const toggleType = (t: QuestionType) =>
    setTypes((prev) => (prev.includes(t) ? (prev.length > 1 ? prev.filter((x) => x !== t) : prev) : [...prev, t]));

  async function generate() {
    setLoading(true);
    try {
      const quiz = await api.quizzes.generate(course.id, {
        num_questions: count,
        difficulty,
        question_types: types,
        topic: topic || null,
        document_ids: scope.length ? scope : null,
      });
      toast.success(`Generated ${quiz.question_count} questions`);
      onCreated(quiz);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="h-fit p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Sparkles className="h-4 w-4 text-indigo-600" /> Generate a quiz
      </h2>
      <p className="mt-1 text-xs text-slate-500">Questions are written only from your materials and cite their source.</p>
      <div className="mt-5 space-y-5">
        <Field label={`Questions: ${count}`}>
          <input type="range" min={1} max={20} value={count} onChange={(e) => setCount(Number(e.target.value))} className="w-full accent-indigo-600" />
        </Field>
        <div>
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Difficulty</span>
          <Segmented
            value={difficulty}
            onChange={setDifficulty}
            options={[
              { value: "easy", label: "Easy" },
              { value: "medium", label: "Medium" },
              { value: "hard", label: "Hard" },
            ]}
          />
        </div>
        <div>
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Question types</span>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(TYPE_LABELS) as QuestionType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => toggleType(t)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs font-medium ring-1 transition",
                  types.includes(t) ? "bg-indigo-50 text-indigo-700 ring-indigo-200" : "bg-white text-slate-500 ring-slate-200 hover:text-slate-800",
                )}
              >
                {TYPE_LABELS[t]}
              </button>
            ))}
          </div>
        </div>
        <Field label="Focus topic" hint="Optional — e.g. “learning rate schedules”. Leave empty to cover everything.">
          <Input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200} placeholder="Any topic" />
        </Field>
        <div>
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Materials</span>
          <DocumentScope documents={readyDocuments} value={scope} onChange={setScope} />
        </div>
        <Button className="w-full" onClick={generate} loading={loading} disabled={!readyDocuments.length}>
          {loading ? "Writing questions…" : "Generate quiz"}
        </Button>
        {!readyDocuments.length && <p className="text-center text-xs text-slate-500">Upload materials first.</p>}
      </div>
    </Card>
  );
}

function QuizPlayer({ quiz, onExit }: { quiz: QuizDetail; onExit: () => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const answered = quiz.questions.filter((q) => answers[q.id]?.trim()).length;
  const resultFor = (id: string) => attempt?.results.find((r) => r.question_id === id);

  async function submit() {
    if (answered < quiz.questions.length && !window.confirm("Some questions are unanswered. Submit anyway?")) return;
    setSubmitting(true);
    try {
      setAttempt(await api.quizzes.submit(quiz.id, answers));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <button onClick={onExit} className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> All quizzes
      </button>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">{quiz.title}</h2>
          <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">
            <Badge tone={DIFFICULTY_TONE[quiz.difficulty]}>{quiz.difficulty}</Badge>
            {quiz.questions.length} questions · generated by {quiz.generator.split(":")[0]}
          </p>
        </div>
      </div>

      {attempt && (
        <Card className="mb-6 flex items-center gap-5 p-5">
          <div
            className={cn(
              "flex h-16 w-16 items-center justify-center rounded-2xl text-white",
              attempt.score >= 80 ? "bg-emerald-500" : attempt.score >= 50 ? "bg-amber-500" : "bg-rose-500",
            )}
          >
            <Trophy className="h-7 w-7" />
          </div>
          <div className="flex-1">
            <p className="text-2xl font-semibold text-slate-900 tabular-nums">{Math.round(attempt.score)}%</p>
            <p className="text-sm text-slate-500">
              {attempt.correct_count} of {attempt.total} correct. Review the explanations and sources below.
            </p>
          </div>
          <Button
            variant="outline"
            icon={<RotateCcw className="h-4 w-4" />}
            onClick={() => {
              setAttempt(null);
              setAnswers({});
            }}
          >
            Retake
          </Button>
        </Card>
      )}

      <ol className="space-y-4">
        {quiz.questions.map((q, i) => {
          const result = resultFor(q.id);
          const value = answers[q.id] ?? "";
          return (
            <Card
              key={q.id}
              className={cn(
                "p-5",
                result && (result.correct ? "ring-1 ring-emerald-200" : result.score > 0 ? "ring-1 ring-amber-200" : "ring-1 ring-rose-200"),
              )}
            >
              <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
                <span className="font-semibold text-slate-700">Q{i + 1}</span>
                <Badge>{TYPE_LABELS[q.question_type]}</Badge>
                {result &&
                  (result.correct ? (
                    <Badge tone="emerald">
                      <CheckCircle2 className="h-3 w-3" /> Correct
                    </Badge>
                  ) : result.score > 0 ? (
                    <Badge tone="amber">Partially correct</Badge>
                  ) : (
                    <Badge tone="rose">
                      <XCircle className="h-3 w-3" /> Incorrect
                    </Badge>
                  ))}
              </div>
              <Markdown content={q.prompt} className="font-medium text-slate-900" />

              <div className="mt-4">
                {q.question_type === "short_answer" ? (
                  <Textarea
                    rows={3}
                    value={value}
                    disabled={!!attempt}
                    onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                    placeholder="Write your answer…"
                  />
                ) : (
                  <div className={cn("grid gap-2", q.question_type === "true_false" && "grid-cols-2")}>
                    {q.options.map((option, idx) => {
                      const selected = value === option;
                      const isCorrect = result && option === result.correct_answer;
                      const isWrongPick = result && selected && !result.correct;
                      return (
                        <button
                          key={option}
                          type="button"
                          disabled={!!attempt}
                          onClick={() => setAnswers((a) => ({ ...a, [q.id]: option }))}
                          className={cn(
                            "flex items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left text-sm transition",
                            isCorrect
                              ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                              : isWrongPick
                                ? "border-rose-300 bg-rose-50 text-rose-900"
                                : selected
                                  ? "border-indigo-400 bg-indigo-50 text-indigo-900"
                                  : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
                          )}
                        >
                          {q.question_type === "mcq" && (
                            <span
                              className={cn(
                                "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
                                selected ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-500",
                              )}
                            >
                              {String.fromCharCode(65 + idx)}
                            </span>
                          )}
                          <span>{option}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {result && (
                <div className="mt-4 space-y-3 rounded-xl bg-slate-50 p-4 text-sm">
                  {q.question_type === "short_answer" && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 uppercase">Model answer</p>
                      <p className="mt-1 text-slate-800">{result.correct_answer}</p>
                      {result.feedback && <p className="mt-1 text-xs text-slate-500">{result.feedback}</p>}
                    </div>
                  )}
                  {result.explanation && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 uppercase">Explanation</p>
                      <Markdown content={result.explanation} className="mt-1 text-sm" />
                    </div>
                  )}
                  {result.source && <SourceCard source={result.source} compact />}
                </div>
              )}
            </Card>
          );
        })}
      </ol>

      {!attempt && (
        <div className="sticky bottom-4 mt-6 flex items-center justify-between rounded-2xl border border-slate-200 bg-white/90 px-5 py-3 shadow-lg backdrop-blur">
          <span className="text-sm text-slate-600">
            {answered} / {quiz.questions.length} answered
          </span>
          <Button onClick={submit} loading={submitting} icon={<ClipboardCheck className="h-4 w-4" />}>
            Submit answers
          </Button>
        </div>
      )}
    </div>
  );
}
