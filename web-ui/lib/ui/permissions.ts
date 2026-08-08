import type { CurrentUser } from "./types";

const ADMIN_ROLES = new Set(["admin", "tenant_admin", "root_admin"]);

export function isAdmin(user?: CurrentUser | null): boolean {
  if (!user) return false;
  return ADMIN_ROLES.has(user.rawRole ?? "") || Boolean(user.isSuperAdmin);
}

export function isPlatformAdmin(user?: CurrentUser | null): boolean {
  if (!user) return false;
  return Boolean(user.isSuperAdmin) || user.rawRole === "root_admin";
}

export function canManageDataSourceAssignments(user?: CurrentUser | null): boolean {
  return isAdmin(user);
}

export function canViewSettings(user?: CurrentUser | null): boolean {
  // My Tenant is visible to every authenticated user; other sections are
  // filtered by role in the Settings nav. If a user has any visible Settings
  // item, the Settings entry should appear in the main sidebar.
  return Boolean(user);
}

export function canViewProjectIntelligence(_user?: CurrentUser | null): boolean {
  // Project membership is enforced server-side; the nav item is shown to every
  // authenticated user. A project is selected (or the user is prompted) before
  // any project-scoped data is rendered.
  return Boolean(_user);
}

export function canOperateGraphLifecycle(user?: CurrentUser | null): boolean {
  // Graph rebuild/health mutations are limited to project editors and admins.
  return isAdmin(user);
}
