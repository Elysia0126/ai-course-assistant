import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RegisterForm } from "@/components/auth-forms";
import { safeNextPath } from "@/lib/auth";
import { getSession } from "@/lib/server-auth";

export const metadata: Metadata = { title: "Create an account" };

export default async function RegisterPage({ searchParams }: PageProps<"/register">) {
  const { next } = await searchParams;
  const destination = safeNextPath(Array.isArray(next) ? next[0] : next);
  if ((await getSession()).status === "authenticated") redirect(destination);
  return <RegisterForm next={destination} />;
}
