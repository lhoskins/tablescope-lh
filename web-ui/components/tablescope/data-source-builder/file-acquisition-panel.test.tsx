import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FilePreviewResult } from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { FileAcquisitionPanel } from "./file-acquisition-panel";
import { sessionSourceFromPreview } from "./import-source";

const capabilities = vi.hoisted(() => vi.fn());
const importFromUrl = vi.hoisted(() => vi.fn());
const importFromNetwork = vi.hoisted(() => vi.fn());
const testNetworkPath = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/data-source-builder", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/data-source-builder")>()),
  getImportCapabilities: capabilities,
  importFromUrl,
  importFromNetwork,
  testNetworkPath,
  analyzeFile: vi.fn(),
}));

const PREVIEW: FilePreviewResult = {
  import_job_id: "job-1",
  upload_session_id: "job-1",
  acquisition_method: "url",
  source_host: "files.example.com",
  file: {
    file_name: "sales.csv",
    file_type: "csv",
    file_size_bytes: 120,
    row_count: 3,
    column_count: 2,
    sheet_name: null,
  },
  fields: [{ field_name: "region" }, { field_name: "units" }],
};

/** Tabs stay disabled until capabilities load, so wait before clicking. */
async function openTab(name: RegExp) {
  const tab = await screen.findByRole("tab", { name });
  await waitFor(() => expect(tab).not.toBeDisabled());
  fireEvent.click(tab);
  return tab;
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FileAcquisitionPanel />
    </QueryClientProvider>,
  );
}

const ALL_ENABLED = {
  local_upload_enabled: true,
  url_import_enabled: true,
  network_import_enabled: true,
  max_file_size_bytes: 104857600,
  malware_scanning_enabled: true,
  network_connections: [
    { id: 4, name: "Finance", label: "\\\\fileserver\\data" },
  ],
};

beforeEach(() => {
  capabilities.mockResolvedValue(ALL_ENABLED);
  importFromUrl.mockReset();
  importFromNetwork.mockReset();
  testNetworkPath.mockReset();
  useBuilderStore.setState({ sources: [], createdKeys: [] });
  window.localStorage.clear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("FileAcquisitionPanel", () => {
  it("offers all three acquisition methods with upload selected first", async () => {
    renderPanel();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Upload file"),
      expect.stringContaining("File URL"),
      expect.stringContaining("Network path"),
    ]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });

  it("expands only the selected method's form", async () => {
    renderPanel();
    expect(screen.queryByLabelText(/File URL \(https only\)/)).toBeNull();
    await openTab(/File URL/);
    expect(screen.getByLabelText(/File URL \(https only\)/)).toBeTruthy();
    expect(screen.queryByLabelText(/Network path/)).toBeNull();
  });

  it("disables methods the deployment has not enabled", async () => {
    capabilities.mockResolvedValue({
      ...ALL_ENABLED,
      url_import_enabled: false,
      network_import_enabled: false,
      network_connections: [],
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /File URL/ })).toBeDisabled(),
    );
    expect(screen.getByRole("tab", { name: /Network path/ })).toBeDisabled();
    expect(screen.getAllByText("Not enabled")).toHaveLength(2);
  });
});

describe("URL import form", () => {
  async function openUrlForm() {
    renderPanel();
    await openTab(/File URL/);
    return screen.getByLabelText(/File URL \(https only\)/);
  }

  it("rejects non-https input before any request is made", async () => {
    const input = await openUrlForm();
    fireEvent.change(input, {
      target: { value: "http://files.example.com/sales.csv" },
    });
    expect(screen.getByText(/full https:\/\/ URL/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Import & analyze/ }),
    ).toBeDisabled();
    expect(importFromUrl).not.toHaveBeenCalled();
  });

  it("previews only the host and file name, never the query string", async () => {
    const input = await openUrlForm();
    fireEvent.change(input, {
      target: {
        value: "https://files.example.com/reports/sales.csv?sig=super-secret",
      },
    });
    expect(screen.getByText(/files\.example\.com/)).toBeTruthy();
    expect(screen.getByText("sales.csv")).toBeTruthy();
    expect(screen.queryByText(/super-secret/)).toBeNull();
  });

  it("adds the imported file to the session and shows the ready stage", async () => {
    importFromUrl.mockResolvedValue(PREVIEW);
    const input = await openUrlForm();
    fireEvent.change(input, {
      target: { value: "https://files.example.com/reports/sales.csv" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import & analyze/ }));

    await waitFor(() => expect(importFromUrl).toHaveBeenCalledTimes(1));
    await screen.findByText("Ready to assign");
    const sources = useBuilderStore.getState().sources;
    expect(sources).toHaveLength(1);
    expect(sources[0].fileMetadata?.acquisitionMethod).toBe("url");
    expect(sources[0].fileMetadata?.importJobId).toBe("job-1");
  });

  it("surfaces a failure with a retry affordance", async () => {
    importFromUrl.mockRejectedValue(new Error("That host is not permitted."));
    const input = await openUrlForm();
    fireEvent.change(input, {
      target: { value: "https://files.example.com/reports/sales.csv" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import & analyze/ }));

    await screen.findByText("That host is not permitted.");
    expect(screen.getByRole("button", { name: /Try again/ })).toBeTruthy();
    expect(useBuilderStore.getState().sources).toHaveLength(0);
  });
});

describe("Network import form", () => {
  async function openNetworkForm() {
    renderPanel();
    await openTab(/Network path/);
    return screen.getByLabelText("Network path");
  }

  it("offers saved credentials by name only, with no password field", async () => {
    await openNetworkForm();
    expect(screen.getByLabelText("Saved credential")).toBeTruthy();
    expect(
      screen.getByRole("option", { name: /Finance/ }),
    ).toBeTruthy();
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });

  it("requires a UNC or smb:// path", async () => {
    const input = await openNetworkForm();
    fireEvent.change(input, { target: { value: "/home/me/sales.csv" } });
    expect(screen.getByText(/Use a UNC path/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Import & analyze/ }),
    ).toBeDisabled();
  });

  it("imports an approved path and records the network origin", async () => {
    importFromNetwork.mockResolvedValue({
      ...PREVIEW,
      acquisition_method: "network_path",
      source_host: "fileserver",
    });
    const input = await openNetworkForm();
    fireEvent.change(input, {
      target: { value: "\\\\fileserver\\data\\finance\\sales.csv" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import & analyze/ }));

    await waitFor(() =>
      expect(importFromNetwork).toHaveBeenCalledWith(
        4,
        "\\\\fileserver\\data\\finance\\sales.csv",
      ),
    );
    const source = useBuilderStore.getState().sources[0];
    expect(source.fileMetadata?.acquisitionMethod).toBe("network_path");
    expect(source.fileMetadata?.sourceHost).toBe("fileserver");
  });

  it("explains that no approved locations exist yet", async () => {
    capabilities.mockResolvedValue({ ...ALL_ENABLED, network_connections: [] });
    renderPanel();
    await openTab(/Network path/);
    expect(screen.getByText(/No approved network locations yet/)).toBeTruthy();
  });
});

describe("persisted builder state", () => {
  it("keeps locators and credentials out of localStorage", () => {
    const source = sessionSourceFromPreview({
      ...PREVIEW,
      source_locator_redacted: "https://files.example.com/reports/sales.csv",
    });
    useBuilderStore.setState({ sources: [source], tenantKey: "acme" });
    const persisted = JSON.stringify(
      Object.entries(window.localStorage).map(([, v]) => v),
    );
    expect(persisted).not.toContain("/reports/");
    expect(persisted).not.toContain("password");
    expect(source.fileMetadata?.sourceHost).toBe("files.example.com");
    expect(JSON.stringify(source)).not.toContain("/reports/");
  });
});
