import { describe, expect, it } from "vitest";
import { homeNavGroups } from "./nav";
import type { CurrentUser } from "@/lib/ui/types";

function makeUser(rawRole: string, isSuperAdmin = false): CurrentUser {
  return {
    id: 1,
    name: "Test",
    email: "test@example.com",
    role: rawRole,
    rawRole,
    tenantName: "Acme",
    initials: "T",
    isSuperAdmin,
    avatarUrl: null,
  };
}

describe("homeNavGroups", () => {
  it("places Data Source Assignments after Database Connectors for admin users", () => {
    const groups = homeNavGroups(makeUser("admin"));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).toEqual([
      "data-source-builder",
      "database-connectors",
      "admin-data-source-assignments",
    ]);
  });

  it("does not include Data Source Assignments for regular members", () => {
    const groups = homeNavGroups(makeUser("member"));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).not.toContain("admin-data-source-assignments");
  });

  it("includes Data Source Assignments for super admins", () => {
    const groups = homeNavGroups(makeUser("member", true));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).toContain("admin-data-source-assignments");
  });
});
