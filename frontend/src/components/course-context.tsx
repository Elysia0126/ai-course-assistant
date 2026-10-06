"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "@/lib/api";
import type { Course, CourseDocument } from "@/lib/types";

interface CourseContextValue {
  course: Course;
  documents: CourseDocument[];
  readyDocuments: CourseDocument[];
  refreshCourse: () => Promise<void>;
  refreshDocuments: () => Promise<void>;
  setCourse: (course: Course) => void;
}

const CourseContext = createContext<CourseContextValue | null>(null);

export function useCourse(): CourseContextValue {
  const value = useContext(CourseContext);
  if (!value) throw new Error("useCourse must be used inside <CourseProvider>");
  return value;
}

const POLL_MS = 1500;

export function CourseProvider({
  courseId,
  children,
  fallback,
  renderError,
}: {
  courseId: string;
  children: ReactNode;
  fallback: ReactNode;
  renderError: (message: string) => ReactNode;
}) {
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshCourse = useCallback(async () => {
    try {
      setCourse(await api.courses.get(courseId));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [courseId]);

  const refreshDocuments = useCallback(async () => {
    try {
      setDocuments(await api.documents.list(courseId));
    } catch {
      /* surfaced by the materials page */
    }
  }, [courseId]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.courses.get(courseId), api.documents.list(courseId)])
      .then(([nextCourse, nextDocuments]) => {
        if (cancelled) return;
        setCourse(nextCourse);
        setDocuments(nextDocuments);
      })
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  // Poll while any document is still being parsed/embedded, then refresh course stats once.
  const busy = documents.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    pollRef.current = setTimeout(async () => {
      const next = await api.documents.list(courseId).catch(() => null);
      if (next) {
        setDocuments(next);
        if (!next.some((d) => d.status === "pending" || d.status === "processing")) refreshCourse();
      }
    }, POLL_MS);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [busy, documents, courseId, refreshCourse]);

  if (error) return <>{renderError(error)}</>;
  if (!course) return <>{fallback}</>;

  return (
    <CourseContext.Provider
      value={{
        course,
        documents,
        readyDocuments: documents.filter((d) => d.status === "ready"),
        refreshCourse,
        refreshDocuments,
        setCourse,
      }}
    >
      {children}
    </CourseContext.Provider>
  );
}
