"use client";

import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  IconArrowUp,
  IconMicrophone,
  IconPlayerStop,
  IconLoader2,
  IconX,
  IconAlertCircle,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { useVoiceRecorder } from "@/hooks/use-voice-recorder";
import { transcribeAudio } from "@/lib/api/voice";

export interface AskAnythingComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  submitAriaLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  /** When false the microphone is hidden entirely. */
  voiceEnabled?: boolean;
  projectId?: number | string | null;
  className?: string;
}

function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function AskAnythingComposer({
  value,
  onChange,
  onSubmit,
  placeholder = "Ask anything…",
  ariaLabel = "Ask anything",
  submitAriaLabel = "Send",
  busy = false,
  disabled = false,
  voiceEnabled = true,
  projectId,
  className,
}: AskAnythingComposerProps) {
  const {
    state: recorderState,
    durationMs,
    start,
    stop,
    cancel,
  } = useVoiceRecorder();
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const canSubmit = value.trim().length > 0 && !busy && !disabled;

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (canSubmit) onSubmit(value);
      }
    },
    [canSubmit, onSubmit, value],
  );

  const handleSubmit = useCallback(() => {
    if (canSubmit) onSubmit(value);
  }, [canSubmit, onSubmit, value]);

  const startRecording = useCallback(async () => {
    cancel();
    setVoiceError(null);
    setIsTranscribing(false);
    await start();
  }, [cancel, start]);

  const stopRecording = useCallback(async () => {
    setIsTranscribing(true);
    try {
      const result = await stop();
      if (!result) return;
      const { transcript } = await transcribeAudio(result.blob, result.mimeType, projectId);
      onChange(value + (value && !value.endsWith(" ") ? " " : "") + transcript);
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Transcription failed");
    } finally {
      setIsTranscribing(false);
      cancel();
      textareaRef.current?.focus();
    }
  }, [stop, cancel, value, onChange, projectId]);

  useEffect(() => {
    return () => {
      cancel();
    };
  }, [cancel]);

  const isRecording = recorderState === "recording";
  const isProcessing = isTranscribing || recorderState === "processing";

  const showMic = voiceEnabled && !isRecording && !isProcessing;
  const showUnsupported = recorderState === "unsupported";
  const showDenied = recorderState === "denied";

  return (
    <div className={cn("w-full", className)}>
      <div
        className={cn(
          "flex items-end gap-2 rounded-xl border bg-bg-primary px-3 py-2.5 transition-shadow focus-within:ring-2 focus-within:ring-brand-100",
          isRecording
            ? "border-danger ring-2 ring-danger/30"
            : "border-line-secondary",
        )}
      >
        <AutosizeTextarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          minRows={1}
          maxRows={8}
          placeholder={placeholder}
          aria-label={ariaLabel}
          disabled={disabled || busy || isRecording || isProcessing}
          className="min-w-0 flex-1 resize-none bg-transparent text-[14px] text-ink-primary outline-none placeholder:text-ink-tertiary disabled:opacity-60"
        />

        {isRecording && (
          <div className="flex shrink-0 items-center gap-2 text-[13px] text-danger">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-danger opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-danger" />
            </span>
            <span className="tabular-nums">{formatDuration(durationMs)}</span>
          </div>
        )}

        {showMic && (
          <button
            type="button"
            onClick={startRecording}
            disabled={disabled || busy}
            title="Speak your question"
            aria-label="Speak your question"
            className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary transition-colors hover:bg-brand-50 hover:text-brand-700 disabled:opacity-40"
          >
            <IconMicrophone size={18} />
          </button>
        )}

        {isRecording && (
          <button
            type="button"
            onClick={stopRecording}
            title="Stop recording"
            aria-label="Stop recording"
            className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-danger text-white transition-colors hover:bg-danger/90"
          >
            <IconPlayerStop size={18} />
          </button>
        )}

        {isProcessing && (
          <div className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary">
            <IconLoader2 size={18} className="animate-spin" />
          </div>
        )}

        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-label={submitAriaLabel}
          className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-brand text-brand-fg transition-colors hover:bg-brand-700 disabled:opacity-40"
        >
          {busy ? (
            <IconLoader2 size={16} className="animate-spin" />
          ) : (
            <IconArrowUp size={18} />
          )}
        </button>
      </div>

      {(showUnsupported || showDenied || voiceError) && (
        <div className="mt-1.5 flex items-start gap-1.5 text-[12px] text-ink-secondary">
          <IconAlertCircle size={14} className="mt-0.5 shrink-0 text-warning" />
          <span>
            {showUnsupported && "Voice input is not supported in this browser. You can still type your question."}
            {showDenied && "Microphone access was denied. Enable it in your browser settings to use voice input."}
            {voiceError}
          </span>
          <button
            type="button"
            onClick={() => {
              setVoiceError(null);
              cancel();
            }}
            className="ml-auto shrink-0 text-ink-tertiary hover:text-ink-primary"
            aria-label="Dismiss"
          >
            <IconX size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
