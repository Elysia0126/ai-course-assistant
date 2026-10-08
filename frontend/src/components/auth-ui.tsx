"use client";

import { AlertCircle, CheckCircle2, Eye, EyeOff, Info } from "lucide-react";
import { type InputHTMLAttributes, type ReactNode, useId, useState } from "react";

import { Card, Input } from "@/components/ui";
import { cn } from "@/lib/format";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex flex-1 items-start justify-center px-4 py-10 sm:items-center sm:py-16">
      <Card className="w-full max-w-md p-6 sm:p-8">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
        <div className="mt-6">{children}</div>
        {footer && <div className="mt-6 border-t border-slate-100 pt-4 text-center text-sm text-slate-500">{footer}</div>}
      </Card>
    </div>
  );
}

const NOTICE_TONES = {
  error: { box: "border-rose-200 bg-rose-50 text-rose-700", icon: AlertCircle },
  success: { box: "border-emerald-200 bg-emerald-50 text-emerald-800", icon: CheckCircle2 },
  info: { box: "border-indigo-200 bg-indigo-50 text-indigo-800", icon: Info },
} as const;

export function Notice({ tone = "info", children }: { tone?: keyof typeof NOTICE_TONES; children: ReactNode }) {
  const { box, icon: Icon } = NOTICE_TONES[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("mb-4 flex gap-2 rounded-lg border px-3 py-2.5 text-sm", box)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & { label: string; hint?: string; error?: string };

function Described({ id, hint, error }: { id: string; hint?: string; error?: string }) {
  if (error) return <p id={`${id}-message`} className="mt-1 text-xs text-rose-600">{error}</p>;
  if (hint) return <p id={`${id}-message`} className="mt-1 text-xs text-slate-500">{hint}</p>;
  return null;
}

export function TextField({ label, hint, error, className, ...props }: FieldProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}
      </label>
      <Input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? `${id}-message` : undefined}
        className={cn(error && "border-rose-300 focus:border-rose-400 focus:ring-rose-100", className)}
        {...props}
      />
      <Described id={id} hint={hint} error={error} />
    </div>
  );
}

/** Password input with a show/hide toggle. Never trimmed, works with password managers. */
export function PasswordField({ label, hint, error, className, ...props }: FieldProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          spellCheck={false}
          autoCapitalize="none"
          autoCorrect="off"
          aria-invalid={error ? true : undefined}
          aria-describedby={hint || error ? `${id}-message` : undefined}
          className={cn("pr-10", error && "border-rose-300 focus:border-rose-400 focus:ring-rose-100", className)}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((value) => !value)}
          aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-controls={id}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-slate-400 hover:text-slate-600"
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      <Described id={id} hint={hint} error={error} />
    </div>
  );
}
