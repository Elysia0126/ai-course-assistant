"use client";

import { Check } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { COURSE_COLORS, cn } from "@/lib/format";
import type { Course, CourseColor } from "@/lib/types";

import { Button, Field, Input, Modal, Textarea } from "./ui";

const COLORS = Object.keys(COURSE_COLORS) as CourseColor[];

export function CourseFormDialog({
  open,
  onClose,
  onSaved,
  course,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (course: Course) => void;
  course?: Course;
}) {
  const [name, setName] = useState(course?.name ?? "");
  const [code, setCode] = useState(course?.code ?? "");
  const [term, setTerm] = useState(course?.term ?? "");
  const [description, setDescription] = useState(course?.description ?? "");
  const [color, setColor] = useState<CourseColor>(course?.color ?? "indigo");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      const input = { name, code: code || null, term: term || null, description: description || null, color };
      const saved = course ? await api.courses.update(course.id, input) : await api.courses.create(input);
      toast.success(course ? "Course updated" : "Course created");
      onSaved(saved);
      onClose();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={course ? "Edit course" : "New course"}
      description="Group lecture slides, notes and readings for one class."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="course-form" loading={saving} disabled={!name.trim()}>
            {course ? "Save changes" : "Create course"}
          </Button>
        </>
      }
    >
      <form id="course-form" onSubmit={submit} className="space-y-4">
        <Field label="Course name">
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Machine Learning Foundations" maxLength={200} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Code">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="CS 4780" maxLength={50} />
          </Field>
          <Field label="Term">
            <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Fall 2026" maxLength={50} />
          </Field>
        </div>
        <Field label="Description" hint="Optional — shown on the course card.">
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={2000} />
        </Field>
        <div>
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Color</span>
          <div className="flex gap-2">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                aria-label={c}
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-white ring-offset-2 transition",
                  COURSE_COLORS[c].dot,
                  color === c && cn("ring-2", COURSE_COLORS[c].ring),
                )}
              >
                {color === c && <Check className="h-3.5 w-3.5" />}
              </button>
            ))}
          </div>
        </div>
      </form>
    </Modal>
  );
}
