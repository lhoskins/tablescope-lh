"use client";

import { create } from "zustand";
import type { InsightCard, ReportSection } from "@/lib/api/home-intelligence";

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

interface ReportBuilderState {
  open: boolean;
  title: string;
  sections: ReportSection[];
  /** Cache of insight cards by section id for in-panel previews. */
  previews: Record<string, InsightCard>;

  openPanel: () => void;
  closePanel: () => void;
  setTitle: (title: string) => void;
  addInsightCard: (card: InsightCard) => void;
  addTextBlock: () => void;
  updateTextBlock: (id: string, text: string) => void;
  removeSection: (id: string) => void;
  reorderSections: (from: number, to: number) => void;
  reset: () => void;
}

export const useReportBuilder = create<ReportBuilderState>((set) => ({
  open: false,
  title: "Untitled report",
  sections: [],
  previews: {},

  openPanel: () => set({ open: true }),
  closePanel: () => set({ open: false }),
  setTitle: (title) => set({ title }),

  addInsightCard: (card) =>
    set((state) => {
      // De-dupe: same project + insight type already added.
      const exists = state.sections.some(
        (s) =>
          s.kind === "insight" &&
          s.insight?.projectId === card.projectId &&
          s.insight?.insightType === card.insightType,
      );
      if (exists) return { open: true };
      const id = uid();
      const section: ReportSection = {
        id,
        kind: "insight",
        insight: {
          projectId: card.projectId,
          projectName: card.projectName,
          insightType: card.insightType,
          title: card.title,
        },
      };
      return {
        open: true,
        sections: [...state.sections, section],
        previews: { ...state.previews, [id]: card },
      };
    }),

  addTextBlock: () =>
    set((state) => ({
      sections: [
        ...state.sections,
        { id: uid(), kind: "text", text: "" },
      ],
    })),

  updateTextBlock: (id, text) =>
    set((state) => ({
      sections: state.sections.map((s) =>
        s.id === id ? { ...s, text } : s,
      ),
    })),

  removeSection: (id) =>
    set((state) => {
      const previews = { ...state.previews };
      delete previews[id];
      return {
        sections: state.sections.filter((s) => s.id !== id),
        previews,
      };
    }),

  reorderSections: (from, to) =>
    set((state) => {
      if (
        from < 0 ||
        to < 0 ||
        from >= state.sections.length ||
        to >= state.sections.length
      ) {
        return {};
      }
      const next = [...state.sections];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return { sections: next };
    }),

  reset: () =>
    set({ title: "Untitled report", sections: [], previews: {} }),
}));
