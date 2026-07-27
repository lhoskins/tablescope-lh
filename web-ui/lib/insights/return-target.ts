"use client";

import { useEffect, useState } from "react";

/**
 * The insight a reader is returning to, taken from the URL hash.
 *
 * Coming back from a card's full analysis used to land on a freshly-mounted
 * feed: panels collapsed, scrolled to the top, the card that prompted the
 * drill-down nowhere in sight. Browser history cannot fix that on its own —
 * `InsightPanel` holds its open state locally, so any remount resets it.
 *
 * Carrying the id in the hash makes the return deterministic: the panel holding
 * that card opens, and the card is scrolled into view. It also makes the
 * position shareable, the same way the analysis route is.
 */
export const RETURN_HASH_PREFIX = "insight-";

/** DOM id for a card, so the hash can address it. */
export function insightAnchorId(insightId: string): string {
  return `${RETURN_HASH_PREFIX}${insightId}`;
}

/** Link back to the feed, positioned on the card the analysis came from. */
export function insightReturnHref(basePath: string, insightId: string): string {
  if (!insightId) return basePath;
  return `${basePath}#${insightAnchorId(encodeURIComponent(insightId))}`;
}

/**
 * The insight id in the current hash, or `null`.
 *
 * Read in an effect rather than during render: the hash is not available during
 * SSR, and reading it while rendering would desynchronise hydration.
 */
export function useReturnTarget(): string | null {
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    const read = () => {
      const hash = window.location.hash.slice(1);
      setTarget(
        hash.startsWith(RETURN_HASH_PREFIX)
          ? decodeURIComponent(hash.slice(RETURN_HASH_PREFIX.length))
          : null,
      );
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  return target;
}

/**
 * Scroll the targeted card into view once it exists.
 *
 * The feed renders asynchronously, so the element is usually absent on the
 * first pass — the browser's own hash scrolling fires too early and does
 * nothing. This retries on a short observer until the node appears, then stops.
 */
export function useScrollToReturnTarget(target: string | null, ready: boolean): void {
  useEffect(() => {
    if (!target || !ready) return;
    let cancelled = false;

    const attempt = () => {
      if (cancelled) return true;
      const el = document.getElementById(insightAnchorId(target));
      if (!el) return false;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      // A brief highlight, so the eye lands on the right card in a dense feed.
      el.setAttribute("data-returned", "true");
      window.setTimeout(() => el.removeAttribute("data-returned"), 2000);
      return true;
    };

    if (attempt()) return;
    const interval = window.setInterval(() => {
      if (attempt()) window.clearInterval(interval);
    }, 120);
    const stop = window.setTimeout(() => window.clearInterval(interval), 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.clearTimeout(stop);
    };
  }, [target, ready]);
}
