"use client";

import { useState, useRef, useCallback, useEffect } from "react";

interface SpeechRecognitionResult {
  readonly 0: { readonly transcript: string };
}
interface SpeechRecognitionResultList {
  readonly length: number;
  readonly [index: number]: SpeechRecognitionResult;
}
interface SpeechRecognitionResultEvent {
  readonly results: SpeechRecognitionResultList;
}
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

type Props = {
  placeholder?: string;
  submitLabel?: string;
  onSubmit: (prompt: string) => void;
  loading?: boolean;
  disabled?: boolean;
};

export function AIPromptBar({
  placeholder = "Describe what you want to generate…",
  submitLabel = "Generate",
  onSubmit,
  loading = false,
  disabled = false,
}: Props) {
  const [prompt, setPrompt] = useState("");
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }
  }, [prompt]);

  const toggleListening = useCallback(() => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRec =
      typeof window !== "undefined"
        ? (window as unknown as Record<string, unknown>).SpeechRecognition ??
          (window as unknown as Record<string, unknown>).webkitSpeechRecognition
        : null;

    if (!SpeechRec) {
      alert("Speech recognition is not supported in this browser.");
      return;
    }

    const recognition = new (SpeechRec as new () => SpeechRecognitionLike)();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onresult = (event: SpeechRecognitionResultEvent) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      setPrompt(transcript);
    };

    recognition.onerror = () => {
      setListening(false);
    };

    recognition.onend = () => {
      setListening(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [listening]);

  const handleSubmit = () => {
    const text = prompt.trim();
    if (!text || loading || disabled) return;
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
    }
    onSubmit(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex items-end gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-400">
      <textarea
        ref={textareaRef}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
        disabled={disabled || loading}
        className="min-h-[36px] flex-1 resize-none border-0 bg-transparent text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-0 disabled:opacity-50"
      />

      <div className="flex items-center gap-1.5 pb-0.5">
        {/* Microphone button */}
        <button
          type="button"
          onClick={toggleListening}
          disabled={disabled || loading}
          title={listening ? "Stop listening" : "Voice input"}
          className={`rounded-full p-2 transition-colors ${
            listening
              ? "bg-red-500 text-white animate-pulse"
              : "bg-blue-500 text-white hover:bg-blue-600"
          } disabled:opacity-40`}
        >
          <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
            {listening ? (
              /* Stop icon */
              <rect x="6" y="6" width="12" height="12" rx="1" />
            ) : (
              /* Microphone icon */
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
            )}
          </svg>
        </button>

        {/* Submit button */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!prompt.trim() || loading || disabled}
          title={submitLabel}
          className="rounded-full bg-blue-600 p-2 text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
        >
          {loading ? (
            <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
