import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const put = vi.fn();
const post = vi.fn();
const del = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: (...a: unknown[]) => get(...a),
    put: (...a: unknown[]) => put(...a),
    post: (...a: unknown[]) => post(...a),
    delete: (...a: unknown[]) => del(...a),
  },
}));

import AllowedDomainsPage from "./page";

function renderPage() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <AllowedDomainsPage />
    </QueryClientProvider>,
  );
}

describe("AllowedDomainsPage", () => {
  beforeEach(() => {
    get.mockReset();
    put.mockReset();
    post.mockReset();
    del.mockReset();
  });

  it("renders the toggle and the domain list", async () => {
    get.mockResolvedValue({
      enabled: true,
      domains: [
        { id: 1, domain: "boeing.com", is_active: true },
        { id: 2, domain: "safran-group.com", is_active: true },
      ],
    });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("boeing.com")).toBeTruthy(),
    );
    expect(screen.getByText("safran-group.com")).toBeTruthy();
    const toggle = screen.getByRole("switch", {
      name: /enable allowed domains/i,
    });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("rejects an invalid domain without calling the API", async () => {
    get.mockResolvedValue({ enabled: false, domains: [] });
    renderPage();
    await waitFor(() => screen.getByPlaceholderText("boeing.com"));

    fireEvent.change(screen.getByPlaceholderText("boeing.com"), {
      target: { value: "not a domain*" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() =>
      expect(screen.getByText(/valid bare domain/i)).toBeTruthy(),
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("adds a valid domain via the API", async () => {
    get.mockResolvedValue({ enabled: false, domains: [] });
    post.mockResolvedValue({ id: 9, domain: "tablescope.ai", is_active: true });
    renderPage();
    await waitFor(() => screen.getByPlaceholderText("boeing.com"));

    fireEvent.change(screen.getByPlaceholderText("boeing.com"), {
      target: { value: "tablescope.ai" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith(
      "/api/tenants/current/allowed-domains",
      { domain: "tablescope.ai" },
    );
  });
});
