import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const upload = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: { upload: (...args: unknown[]) => upload(...args) },
  getApiBaseUrl: () => "http://api.test",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => ({ data: [] }),
}));

import { Sidebar } from "./sidebar";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

const tenant: TenantSummary = { name: "Acme", slug: "acme", initials: "AC" };

function baseUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    name: "Jane Doe",
    email: "jane@acme.com",
    role: "Member",
    rawRole: "member",
    tenantName: "Acme",
    initials: "JD",
    id: 7,
    avatarUrl: null,
    ...overrides,
  };
}

function renderSidebar(user: CurrentUser) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <Sidebar mode="home" activeNav="home" tenant={tenant} user={user} />
    </QueryClientProvider>,
  );
}

describe("Sidebar avatar uploader", () => {
  beforeEach(() => upload.mockReset());

  it("renders fallback initials when there is no avatar", () => {
    renderSidebar(baseUser());
    const button = screen.getByRole("button", {
      name: /change profile picture/i,
    });
    expect(button.textContent).toContain("JD");
    expect(button.querySelector("img")).toBeNull();
  });

  it("renders the avatar image when avatarUrl is set", () => {
    renderSidebar(baseUser({ avatarUrl: "http://api.test/api/users/7/avatar" }));
    const img = screen
      .getByRole("button", { name: /change profile picture/i })
      .querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe(
      "http://api.test/api/users/7/avatar",
    );
  });

  it("clicking the avatar opens the file picker and uploads the chosen file", async () => {
    upload.mockResolvedValue({ avatar_url: "/api/users/7/avatar?v=abc" });
    const { container } = renderSidebar(baseUser());

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click");

    fireEvent.click(
      screen.getByRole("button", { name: /change profile picture/i }),
    );
    expect(clickSpy).toHaveBeenCalled();

    const file = new File(["x"], "me.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith("/api/users/me/avatar", file);
  });
});

describe("Sidebar nav", () => {
  it("renders Projects as a disclosure toggle, not a navigation link", () => {
    renderSidebar(baseUser());
    const projectsButton = screen.getByRole("button", { name: /Projects/ });
    expect(projectsButton.closest("a")).toBeNull();
  });

  it("keeps the same core items in project mode instead of swapping the link set", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <Sidebar
          mode="project"
          activeNav="overview"
          tenant={tenant}
          user={baseUser()}
          project={{
            id: "7",
            name: "Acme Project",
            visibility: "private",
            accent: "#111",
            documentCount: 0,
            queryCount: 0,
            dashboardCount: 0,
            aiStatus: "idle",
            updatedLabel: "",
          }}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: /^Home/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Business Insight/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /AI Assistant/ })).toBeTruthy();
    expect(screen.queryByText("Other Projects")).toBeNull();
  });
});
