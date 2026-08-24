"use client";

import { useEffect, useRef, useState } from "react";
import { IconPlus, IconSettings2, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import type { HomePersona } from "@/lib/api/home-intelligence";
import { HOME_PERSONAS } from "./home-persona";

export function HomeSettingsDialog({
  open,
  persona,
  focusItems,
  saving,
  onClose,
  onSave,
}: {
  open: boolean;
  persona: HomePersona;
  focusItems: string[];
  saving: boolean;
  onClose: () => void;
  onSave: (settings: { persona: HomePersona; focusItems: string[] }) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [draftPersona, setDraftPersona] = useState<HomePersona>(persona);
  const [draftFocus, setDraftFocus] = useState<string[]>(focusItems);
  const [focusInput, setFocusInput] = useState("");

  useEffect(() => {
    if (!open) return;
    setDraftPersona(persona);
    setDraftFocus(focusItems);
    setFocusInput("");
  }, [focusItems, open, persona]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  function addFocus() {
    const value = focusInput.trim();
    if (
      !value ||
      draftFocus.some((item) => item.toLowerCase() === value.toLowerCase())
    ) {
      return;
    }
    setDraftFocus((items) => [...items, value]);
    setFocusInput("");
    inputRef.current?.focus();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 pt-16"
      role="dialog"
      aria-modal="true"
      aria-labelledby="home-settings-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2
              id="home-settings-title"
              className="flex items-center gap-2 text-h2 text-ink-primary"
            >
              <IconSettings2 size={18} className="text-brand-500" />
              Home settings
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              Control the perspective and topics Tablescope uses to prioritize
              your personal briefing.
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close Home settings">
            <IconX size={17} />
          </Button>
        </div>

        <div className="mt-5 border-t border-line-tertiary pt-5">
          <label htmlFor="home-persona" className="text-[13px] font-medium text-ink-primary">
            Persona
          </label>
          <p className="mt-1 text-small leading-relaxed text-ink-tertiary">
            Persona changes the analytical lens, terminology, and ranking. It
            never expands your tenant, project, document, table, or row access.
          </p>
          <select
            id="home-persona"
            value={draftPersona}
            onChange={(event) => setDraftPersona(event.target.value as HomePersona)}
            className="mt-3 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          >
            {HOME_PERSONAS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-5 border-t border-line-tertiary pt-5">
          <label htmlFor="home-focus" className="text-[13px] font-medium text-ink-primary">
            Focus topics
          </label>
          <p className="mt-1 text-small leading-relaxed text-ink-tertiary">
            Add decisions, risks, KPIs, business questions, or document topics
            that should receive extra weight within the selected persona.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {draftFocus.map((item) => (
              <span
                key={item}
                className="inline-flex h-8 items-center gap-1.5 rounded-full bg-bg-secondary px-3 text-small text-ink-primary"
              >
                {item}
                <button
                  type="button"
                  aria-label={`Remove ${item}`}
                  onClick={() =>
                    setDraftFocus((items) => items.filter((candidate) => candidate !== item))
                  }
                  className="text-ink-tertiary hover:text-ink-primary"
                >
                  <IconX size={13} />
                </button>
              </span>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <input
              ref={inputRef}
              id="home-focus"
              value={focusInput}
              onChange={(event) => setFocusInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addFocus();
                }
              }}
              placeholder="Add a focus topic"
              className="h-9 min-w-0 flex-1 rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary outline-none placeholder:text-ink-tertiary focus:border-brand-500"
            />
            <Button variant="secondary" size="md" onClick={addFocus} disabled={!focusInput.trim()}>
              <IconPlus size={14} />
              Add
            </Button>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2 border-t border-line-tertiary pt-4">
          <Button variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            disabled={saving}
            onClick={() => onSave({ persona: draftPersona, focusItems: draftFocus })}
          >
            {saving ? "Saving…" : "Save settings"}
          </Button>
        </div>
      </div>
    </div>
  );
}
