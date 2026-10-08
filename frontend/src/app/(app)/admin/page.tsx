import { ShieldAlert } from "lucide-react";
import type { Metadata } from "next";

import { AdminUsers } from "@/components/admin-users";
import { getSession } from "@/lib/server-auth";

export const metadata: Metadata = { title: "Administration" };

export default async function AdminPage() {
  const session = await getSession();
  // The layout already guarantees a signed-in user; the admin API checks the role again on every call.
  if (session.status !== "authenticated" || session.user.role !== "admin") {
    return (
      <div className="mx-auto w-full max-w-lg px-4 py-24">
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 text-center shadow-xs">
          <ShieldAlert className="mx-auto mb-3 h-6 w-6 text-rose-600" />
          <p className="font-medium text-slate-900">Administrators only</p>
          <p className="mt-1 text-sm text-slate-500">Your account doesn&apos;t have access to this page.</p>
        </div>
      </div>
    );
  }
  return <AdminUsers currentUserId={session.user.id} />;
}
