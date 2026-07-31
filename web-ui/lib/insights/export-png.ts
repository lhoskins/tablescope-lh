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

  const width = article.offsetWidth;
  const clone = article.cloneNode(true) as HTMLElement;

  // Remove interactive/actionable controls from the exported image.
  clone.querySelectorAll('[data-export-hide]').forEach((el) => {
    el.remove();
  });

  clone.style.position = "fixed";
  clone.style.top = "0";
  clone.style.left = "-9999px";
  clone.style.width = `${width}px`;
  clone.style.maxWidth = "none";
  clone.style.zIndex = "-1";
  clone.style.visibility = "visible";

  document.body.appendChild(clone);

  try {
    const dataUrl = await toPng(clone, {
      pixelRatio: 2,
      backgroundColor: "#ffffff",
      cacheBust: true,
    });
    triggerDownload(dataUrl, filename || "insight.png");
  } finally {
    clone.remove();
  }
}
