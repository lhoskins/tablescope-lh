import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-start gap-6 px-6 py-16">
      <h1 className="text-3xl font-bold text-slate-900">Tablescope</h1>
      <p className="text-slate-600">
        Multi-tenant data platform — query your VDBs, configure drill-down
        scopes, and share projects across your organization.
      </p>
      <div className="flex gap-3">
        <Link
          href="/login"
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg shadow-sm hover:opacity-90"
        >
          Sign in
        </Link>
        <Link
          href="/dashboard"
          className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Open dashboard
        </Link>
      </div>
    </main>
  );
}
