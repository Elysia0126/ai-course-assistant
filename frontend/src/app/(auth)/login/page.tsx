import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth-forms";
import { safeNextPath } from "@/lib/auth";
import { getSession } from "@/lib/server-auth";

export const metadata: Metadata = { title: "Sign in" };

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNextPath(first(params.next));
  // Already signed in (FastAPI says so, not just "a cookie exists"): go straight on.
  if ((await getSession()).status === "authenticated") redirect(next);
  return <LoginForm next={next} reason={first(params.reason) ?? null} />;
}
