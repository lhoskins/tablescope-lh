export default function SignupPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-4 text-2xl font-semibold text-slate-900">
        Sign up for Tablescope
      </h1>
      <p className="text-slate-600">
        Signups are provisioned through your auth provider (Clerk / Supabase)
        and linked into Tablescope on first login. Contact your organization
        admin to create an account.
      </p>
    </main>
  );
}
