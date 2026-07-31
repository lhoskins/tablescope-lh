"use client";

import * as echarts from "echarts/core";

function triggerDownload(dataUrl: string, filename: string) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function sanitizeFilename(text: string): string {
  return text.replace(/[^\w\-]/g, "_").replace(/_+/g, "_").slice(0, 60);
}

function inlineSvgStyles(svg: SVGSVGElement): SVGSVGElement {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_ELEMENT);
  let node = walker.nextNode();
  while (node) {
    const el = node as HTMLElement;
    if (el.style) {
      const computed = window.getComputedStyle(el);
      el.style.fontFamily = computed.fontFamily;
      el.style.fontSize = computed.fontSize;
      el.style.fontWeight = computed.fontWeight;
      el.style.fill = computed.fill;
      el.style.stroke = computed.stroke;
      el.style.color = computed.color;
      el.style.backgroundColor = computed.backgroundColor;
    }
    node = walker.nextNode();
  }
  return clone;
}

async function svgToPngDataUrl(svgEl: SVGSVGElement): Promise<string> {
  const rect = svgEl.getBoundingClientRect();
  const widthAttr = svgEl.getAttribute("width");
  const heightAttr = svgEl.getAttribute("height");
  const baseWidth = rect.width || (widthAttr ? parseFloat(widthAttr) : 0) || 800;
  const baseHeight = rect.height || (heightAttr ? parseFloat(heightAttr) : 0) || 600;

  const clone = inlineSvgStyles(svgEl);
  clone.setAttribute("width", String(baseWidth));
  clone.setAttribute("height", String(baseHeight));
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");

  const serializer = new XMLSerializer();
  const svgString = serializer.serializeToString(clone);
  const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  return new Promise((resolve, reject) => {
    const img = new Image();
    const canvas = document.createElement("canvas");
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(baseWidth * ratio));
    canvas.height = Math.max(1, Math.floor(baseHeight * ratio));
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      URL.revokeObjectURL(url);
      reject(new Error("Canvas context unavailable"));
      return;
    }

    img.onload = () => {
      ctx.scale(ratio, ratio);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, baseWidth, baseHeight);
      ctx.drawImage(img, 0, 0, baseWidth, baseHeight);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to render SVG"));
    };
    img.src = url;
  });
}

export function insightPngFilename(card: { projectName?: string; title?: string }): string {
  const parts = [card.projectName, card.title].filter(Boolean);
  return `${sanitizeFilename(parts.join(" - "))}.png`;
}

export async function exportInsightCardPng(
  insightCardId: string,
  filename?: string,
): Promise<void> {
  const article = document.querySelector(
    `[data-insight-card-id="${insightCardId}"]`,
  ) as HTMLElement | null;
  if (!article) {
    throw new Error("Insight card not found");
  }

  const echartsContainer = article.querySelector('[data-chart-renderer="echarts"]') as HTMLElement | null;
  if (echartsContainer) {
    const instance = echarts.getInstanceByDom(echartsContainer);
    if (instance) {
      const dataUrl = instance.getDataURL({
        type: "png",
        pixelRatio: 2,
        backgroundColor: "#ffffff",
      });
      triggerDownload(dataUrl, filename || "insight.png");
      return;
    }
  }

  const svg = article.querySelector("svg") as SVGSVGElement | null;
  if (svg) {
    const dataUrl = await svgToPngDataUrl(svg);
    triggerDownload(dataUrl, filename || "insight.png");
    return;
  }

  throw new Error("No exportable chart found on this insight card");
}
