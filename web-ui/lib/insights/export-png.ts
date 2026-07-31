"use client";

import { toPng } from "html-to-image";

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

  const dataUrl = await toPng(article, {
    pixelRatio: 2,
    backgroundColor: "#ffffff",
    cacheBust: true,
    filter: (node) => {
      if (!(node instanceof HTMLElement)) return true;
      return !node.hasAttribute("data-export-hide");
    },
  });

  triggerDownload(dataUrl, filename || "insight.png");
}
