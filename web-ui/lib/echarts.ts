// ECharts renderer feature gate.
//
// The mode is controlled at build time via NEXT_PUBLIC_ECHARTS_RENDERER_MODE so
// Next.js can tree-shake the ECharts path when the feature is off. Runtime checks
// gate the actual rendering decision.

export type EchartsRendererMode = "off" | "shadow" | "new_widgets" | "default";

const VALID_MODES: EchartsRendererMode[] = ["off", "shadow", "new_widgets", "default"];

export function getEchartsRendererMode(): EchartsRendererMode {
  const raw = process.env.NEXT_PUBLIC_ECHARTS_RENDERER_MODE?.trim().toLowerCase() ?? "off";
  return VALID_MODES.includes(raw as EchartsRendererMode) ? (raw as EchartsRendererMode) : "off";
}

export function isEchartsEnabled(): boolean {
  return getEchartsRendererMode() !== "off";
}

export function shouldRenderEcharts(widgetRenderer?: string): boolean {
  const mode = getEchartsRendererMode();
  if (mode === "off") return false;
  if (mode === "default") return true;
  if (mode === "new_widgets") return widgetRenderer === "echarts";
  if (mode === "shadow") return false; // shadow keeps recharts visible; echarts renders offscreen/behind
  return false;
}
