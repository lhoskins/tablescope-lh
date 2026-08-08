"use client";

import { type ReactNode } from "react";
import { SettingsWorkspace } from "@/components/tablescope/settings/settings-workspace";

export default function SettingsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <SettingsWorkspace>{children}</SettingsWorkspace>;
}
