import { describe, expect, it, vi } from "vitest";
import {
  WORKSPACE_RESOURCE_MIME,
  isResourceDrag,
  readResourceDragData,
  setResourceDragData,
} from "./workspace-drag";

/** jsdom ships no DataTransfer; this records what was written to it. */
function fakeDataTransfer(initial: Record<string, string> = {}) {
  const store = { ...initial };
  return {
    types: Object.keys(store),
    setData: vi.fn((type: string, value: string) => {
      store[type] = value;
    }),
    getData: (type: string) => store[type] ?? "",
    effectAllowed: "all",
    store,
  } as unknown as DataTransfer & { store: Record<string, string> };
}

describe("workspace resource drag", () => {
  it("round-trips a resource through the dataTransfer", () => {
    const dt = fakeDataTransfer();
    setResourceDragData(dt, {
      resource_type: "table",
      resource_id: "3001",
      label: "openai_export_invoice",
    });

    expect(readResourceDragData(dt)).toEqual({
      resource_type: "table",
      resource_id: "3001",
      label: "openai_export_invoice",
    });
    // A text fallback so dropping elsewhere isn't a no-op.
    expect(dt.getData("text/plain")).toBe("openai_export_invoice");
  });

  it("recognises its own payload and nothing else", () => {
    expect(isResourceDrag(fakeDataTransfer({ [WORKSPACE_RESOURCE_MIME]: "{}" }))).toBe(
      true,
    );
    expect(isResourceDrag(fakeDataTransfer({ "text/plain": "hi" }))).toBe(false);
    expect(isResourceDrag(null)).toBe(false);
  });

  it("returns null rather than throwing on a malformed payload", () => {
    // Another app can claim the same MIME type, and a truncated payload must
    // not take the pane down on drop.
    expect(readResourceDragData(fakeDataTransfer({ [WORKSPACE_RESOURCE_MIME]: "{" }))).toBeNull();
    expect(
      readResourceDragData(fakeDataTransfer({ [WORKSPACE_RESOURCE_MIME]: '{"a":1}' })),
    ).toBeNull();
    expect(readResourceDragData(fakeDataTransfer())).toBeNull();
    expect(readResourceDragData(null)).toBeNull();
  });

  it("falls back to the id when a payload carries no label", () => {
    const dt = fakeDataTransfer({
      [WORKSPACE_RESOURCE_MIME]: '{"resource_type":"document","resource_id":"9001"}',
    });
    expect(readResourceDragData(dt)?.label).toBe("9001");
  });
});
