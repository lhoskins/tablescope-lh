import type { ReactNode } from "react";

/**
 * Renders `**bold**` spans in LLM-authored prose as real emphasis instead of
 * literal asterisks.
 *
 * Live finding: chat answers and insight-card summaries came back with text
 * like "**WC-004** leads with **$506,713.68**" rendered verbatim -- every
 * surface showing this kind of free-form model text (`Prose` in
 * ResponsePresenter, insight-card summaries in matched-insight-block) was a
 * plain `<p>{text}</p>`, so the model's own emphasis markup showed up as
 * literal `**` instead of bold. This is intentionally minimal (bold only,
 * no full markdown/HTML parsing) -- the model isn't asked to produce
 * anything richer than that, and rendering to React nodes directly (never
 * `dangerouslySetInnerHTML`) means there's no injection surface to worry
 * about.
 */
const BOLD_RE = /\*\*(.+?)\*\*/g;

export function renderInlineMarkdown(text: string): ReactNode {
  if (!text || !text.includes("**")) return text;

  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  BOLD_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = BOLD_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    nodes.push(<strong key={key++}>{match[1]}</strong>);
    lastIndex = BOLD_RE.lastIndex;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  // No pairs actually matched (e.g. a lone unpaired "**") -- fall back to
  // the raw text rather than an array containing just itself.
  return nodes.length ? nodes : text;
}

export function InlineMarkdown({ text }: { text: string }) {
  return <>{renderInlineMarkdown(text)}</>;
}
