"use client";

import { ArrowLeft, LogIn, Mail, UserPlus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useEffect, useState, useSyncExternalStore } from "react";

import { AuthCard, Notice, PasswordField, TextField } from "@/components/auth-ui";
import { Button } from "@/components/ui";
import { ApiError, api, errorMessage, fieldErrors } from "@/lib/api";
import { PASSWORD_MIN_LENGTH, checkNewPassword } from "@/lib/auth";

type Errors = Record<string, string | undefined>;

const NOTICES: Record<string, { tone: "info" | "success"; text: string }> = {
  expired: { tone: "info", text: "Your session has expired. Please sign in again." },
  "signed-out": { tone: "success", text: "You've been signed out." },
  reset: { tone: "success", text: "Your password has been changed. Sign in with your new password." },
};

const PASSWORD_HINT = `At least ${PASSWORD_MIN_LENGTH} characters. Spaces and any characters work — a passphrase is ideal.`;

/** Server errors: field-level ones go next to their input, the rest above the button. */
function splitErrors(error: unknown): { fields: Errors; form: string | null } {
  const fields: Errors = fieldErrors(error);
  if (error instanceof ApiError && error.code === "email_taken") fields.email = error.message;
  return { fields, form: Object.keys(fields).length ? null : errorMessage(error) };
}

export function LoginForm({ next, reason }: { next: string; reason?: string | null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const notice = reason ? NOTICES[reason] : undefined;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      await api.auth.login({ email, password, remember_me: remember });
      window.location.assign(next); // full load: the server layout re-checks the new session
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Sign in"
      description="Welcome back — your courses, chats and flashcards are waiting."
      footer={
        <>
          New here?{" "}
          <Link href={next === "/" ? "/register" : `/register?${new URLSearchParams({ next })}`} className="font-medium text-indigo-600 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <form onSubmit={submit} noValidate className="space-y-4">
        <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <PasswordField label="Password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <label className="inline-flex items-center gap-2 text-slate-600">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            Remember me
          </label>
          <Link href="/forgot-password" className="font-medium text-indigo-600 hover:underline">
            Forgot password?
          </Link>
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" loading={busy} icon={<LogIn className="h-4 w-4" />} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthCard>
  );
}

export function RegisterForm({ next }: { next: string }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const local: Errors = { ...checkNewPassword(password, confirm) };
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) local.email = "Enter a valid email address.";
    setErrors(local);
    if (Object.values(local).some(Boolean)) return;

    setBusy(true);
    try {
      await api.auth.register({ email, password, password_confirm: confirm, display_name: name.trim() || null });
      window.location.assign(next);
    } catch (err) {
      const { fields, form } = splitErrors(err);
      setErrors(fields);
      setFormError(form);
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Create your account"
      description="Your courses and materials are private to your account."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-indigo-600 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <TextField label="Name (optional)" autoComplete="name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
          required
        />
        <PasswordField
          label="Password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={PASSWORD_HINT}
          error={errors.password}
          required
        />
        <PasswordField
          label="Confirm password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={errors.password_confirm}
          required
        />
        {formError && <Notice tone="error">{formError}</Notice>}
        <Button type="submit" loading={busy} icon={<UserPlus className="h-4 w-4" />} className="w-full">
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Enter the email address of your account.");
      return;
    }
    setBusy(true);
    try {
      setSent((await api.auth.forgotPassword(email)).message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Reset your password"
      description="We'll email you a link to choose a new password."
      footer={
        <Link href="/login" className="inline-flex items-center gap-1 font-medium text-indigo-600 hover:underline">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
        </Link>
      }
    >
      {sent ? (
        <Notice tone="success">{sent}</Notice>
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4">
          <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          {error && <Notice tone="error">{error}</Notice>}
          <Button type="submit" loading={busy} icon={<Mail className="h-4 w-4" />} className="w-full">
            Send reset link
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

// The token arrives in the URL fragment (#token=…), which browsers never send to a server. It is read once
// per page load, then removed from the address bar and history.
let capturedToken: string | null | undefined;

function readResetToken(): string | null {
  if (capturedToken === undefined) {
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("token");
    capturedToken = fromHash ?? new URLSearchParams(window.location.search).get("token");
  }
  return capturedToken;
}

const noSubscription = () => () => {};

export function ResetPasswordForm() {
  const token = useSyncExternalStore(noSubscription, readResetToken, () => undefined);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (token && (window.location.hash || window.location.search)) window.history.replaceState(null, "", window.location.pathname);
  }, [token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const local = checkNewPassword(password, confirm);
    setErrors(local);
    if (Object.values(local).some(Boolean) || !token) return;
    setBusy(true);
    try {
      await api.auth.resetPassword({ token, password, password_confirm: confirm });
      capturedToken = null;
      window.location.replace("/login?reason=reset"); // no automatic sign-in after a reset
    } catch (err) {
      const { fields, form } = splitErrors(err);
      setErrors(fields);
      setFormError(form);
      setBusy(false);
    }
  }

  if (token === undefined) return <AuthCard title="Choose a new password">{null}</AuthCard>;
  if (!token) {
    return (
      <AuthCard title="Choose a new password">
        <Notice tone="error">
          This reset link is incomplete. Open the link from the email again, or{" "}
          <Link href="/forgot-password" className="font-medium underline">
            request a new one
          </Link>
          .
        </Notice>
      </AuthCard>
    );
  }
  return (
    <AuthCard
      title="Choose a new password"
      description="You'll be signed out everywhere and can then sign in with the new password."
      footer={
        <Link href="/forgot-password" className="font-medium text-indigo-600 hover:underline">
          Request a new link
        </Link>
      }
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <PasswordField
          label="New password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={PASSWORD_HINT}
          error={errors.password}
          required
        />
        <PasswordField
          label="Confirm new password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={errors.password_confirm}
          required
        />
        {formError && <Notice tone="error">{formError}</Notice>}
        <Button type="submit" loading={busy} className="w-full">
          Set new password
        </Button>
      </form>
    </AuthCard>
  );
}
