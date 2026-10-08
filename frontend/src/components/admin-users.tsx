"use client";

import { Users } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { AdminUser } from "@/lib/types";

export function AdminUsers({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    api.admin
      .users()
      .then(setUsers)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  async function toggle(user: AdminUser) {
    setPending(user.id);
    try {
      const updated = await api.admin.setActive(user.id, !user.is_active);
      setUsers((list) => list?.map((u) => (u.id === updated.id ? updated : u)) ?? null);
      toast.success(updated.is_active ? `Enabled ${updated.email}` : `Disabled ${updated.email} and signed them out`);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <div className="mb-5 flex items-center gap-2">
        <Users className="h-5 w-5 text-indigo-600" />
        <h1 className="text-lg font-semibold text-slate-900">Accounts</h1>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        Disabling an account signs it out everywhere immediately. Roles are changed with the CLI
        (<code className="rounded bg-slate-100 px-1">python -m app.cli set-role</code>); course content stays private
        to its owner.
      </p>
      {error && <Card className="border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</Card>}
      {!users && !error && (
        <div className="flex justify-center py-16">
          <Spinner className="h-6 w-6" />
        </div>
      )}
      {users && (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Courses</th>
                <th className="px-4 py-3 font-medium">Last sign-in</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{user.display_name || user.email}</div>
                    {user.display_name && <div className="text-xs text-slate-500">{user.email}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={user.role === "admin" ? "indigo" : "slate"}>{user.role}</Badge>
                  </td>
                  <td className="px-4 py-3 tabular-nums text-slate-600">{user.course_count}</td>
                  <td className="px-4 py-3 text-slate-500">{user.last_login_at ? timeAgo(user.last_login_at) : "never"}</td>
                  <td className="px-4 py-3">
                    <Badge tone={user.is_active ? "emerald" : "rose"}>{user.is_active ? "active" : "disabled"}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {user.id !== currentUserId && (
                      <Button
                        size="sm"
                        variant={user.is_active ? "outline" : "secondary"}
                        loading={pending === user.id}
                        onClick={() => toggle(user)}
                      >
                        {user.is_active ? "Disable" : "Enable"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
