import { ReactNode } from "react";

// The Concept A screens (projects list + per-project workspace) render their
// own full-screen shell (AppShell / ProjectShell), so this layout is a simple
// pass-through.
export default function ProjectsLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
