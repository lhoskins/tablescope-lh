export default function DashboardPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
      <p className="mt-2 text-slate-600">
        Welcome to your Tablescope workspace. Use the sidebar to browse
        projects, run queries, and manage drill-down scopes.
      </p>
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        {[
          { name: "Projects", href: "/projects", description: "Manage shared projects" },
          { name: "Run a query", href: "/query", description: "Query your VDB" },
          { name: "Scopes", href: "/scopes", description: "Drill-down config" },
        ].map((card) => (
          <a
            key={card.name}
            href={card.href}
            className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-brand"
          >
            <h2 className="text-base font-medium text-slate-900">{card.name}</h2>
            <p className="text-sm text-slate-500">{card.description}</p>
          </a>
        ))}
      </div>
    </section>
  );
}
