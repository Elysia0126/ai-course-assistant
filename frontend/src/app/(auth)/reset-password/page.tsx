import type { Metadata } from "next";

import { ResetPasswordForm } from "@/components/auth-forms";

// The reset token must never leak through a Referer header (also sent as a response header, see next.config.ts).
export const metadata: Metadata = { title: "Choose a new password", referrer: "no-referrer" };

export default function ResetPasswordPage() {
  return <ResetPasswordForm />;
}
