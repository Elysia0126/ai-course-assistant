import type { ReactNode } from "react";

import { AppHeader } from "@/components/app-header";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <AppHeader />
      <main className="flex flex-1 flex-col bg-gradient-to-b from-indigo-50/60 to-transparent">{children}</main>
    </>
  );
}
