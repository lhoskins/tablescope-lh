import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { clearToken } from "./api-client";
import { signOut } from "./auth";

vi.mock("./api-client", () => ({
  clearToken: vi.fn(),
  apiClient: {},
}));

vi.mock("./supabase", () => ({
  getSupabaseClient: () => ({
    auth: { signOut: vi.fn().mockResolvedValue(undefined) },
  }),
}));

describe("signOut", () => {
  let originalHref: string;

  beforeEach(() => {
    originalHref = window.location.href;
    Object.defineProperty(window, "location", {
      writable: true,
      value: { href: originalHref },
    });
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  function setMeta(slug: string | null) {
    window.localStorage.setItem(
      "tablescope.user_meta",
      JSON.stringify({ tenant_slug: slug }),
    );
  }

  it("redirects a tenant user to the tenant login page by default", () => {
    setMeta("acme");
    signOut();
    expect(clearToken).toHaveBeenCalled();
    expect(window.location.href).toBe("/acme/login");
  });

  it("redirects a tenant user to the tenant root when redirectToRoot is true", () => {
    setMeta("acme");
    signOut({ redirectToRoot: true });
    expect(window.location.href).toBe("/acme");
  });

  it("falls back to /login when no tenant slug is present", () => {
    setMeta(null);
    signOut({ redirectToRoot: true });
    expect(window.location.href).toBe("/login");
  });
});
