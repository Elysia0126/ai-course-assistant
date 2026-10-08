import { ServerCrash } from "lucide-react";

export function ServiceUnavailable() {
  return (
    <div className="mx-auto w-full max-w-lg px-4 py-24">
      <div className="rounded-2xl border border-slate-200/80 bg-white p-6 text-center shadow-xs">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-50 text-rose-600">
          <ServerCrash className="h-5 w-5" />
        </div>
        <p className="font-medium text-slate-900">The study service is unavailable</p>
        <p className="mt-1 text-sm text-slate-500">
          Your session couldn&apos;t be checked because the API isn&apos;t responding. Make sure the backend is running, then
          reload this page.
        </p>
      </div>
    </div>
  );
}
