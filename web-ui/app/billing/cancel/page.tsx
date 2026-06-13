"use client";

import Link from "next/link";

export default function BillingCancelPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 text-center">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">Checkout cancelled</h1>
      <p className="mb-6 text-sm text-slate-600">
        No charge was made and no workspace was created. You can pick a plan whenever
        you&apos;re ready.
      </p>
      <Link
        href="/pricing"
        className="mx-auto rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        Back to pricing
      </Link>
    </main>
  );
}
