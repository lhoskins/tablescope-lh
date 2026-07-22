import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { getEchartsRendererMode, isEchartsEnabled, shouldRenderEcharts } from "./echarts";

describe("echarts feature gate", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("defaults to default when missing or invalid", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "");
    expect(getEchartsRendererMode()).toBe("default");
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "garbage");
    expect(getEchartsRendererMode()).toBe("default");
  });

  it("recognizes off, shadow, new_widgets, and default", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "off");
    expect(getEchartsRendererMode()).toBe("off");
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "  Off  ");
    expect(getEchartsRendererMode()).toBe("off");
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "shadow");
    expect(getEchartsRendererMode()).toBe("shadow");
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "new_widgets");
    expect(getEchartsRendererMode()).toBe("new_widgets");
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "default");
    expect(getEchartsRendererMode()).toBe("default");
  });

  it("is enabled for any non-off mode", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "off");
    expect(isEchartsEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "default");
    expect(isEchartsEnabled()).toBe(true);
  });

  it("renders echarts in default mode for supported widgets", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "default");
    expect(shouldRenderEcharts("recharts")).toBe(true);
    expect(shouldRenderEcharts(undefined)).toBe(true);
  });

  it("renders echarts in new_widgets mode only when renderer is echarts", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "new_widgets");
    expect(shouldRenderEcharts("echarts")).toBe(true);
    expect(shouldRenderEcharts("recharts")).toBe(false);
    expect(shouldRenderEcharts(undefined)).toBe(false);
  });

  it("never renders echarts in off or shadow mode", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "off");
    expect(shouldRenderEcharts("echarts")).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "shadow");
    expect(shouldRenderEcharts("echarts")).toBe(false);
  });
});
