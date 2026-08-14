"use client";

import {
  type DragEvent,
  type KeyboardEvent,
  type ClipboardEvent,
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
  IconPlus,
  IconReload,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { useVoiceRecorder } from "@/hooks/use-voice-recorder";
import { transcribeAudio } from "@/lib/api/voice";
import type { ChatAttachmentSummary } from "@/lib/api/conversational-analytics";

export interface ComposerAttachment {
  id?: number;
  clientId: string;
  file: File;
  original_filename: string;
  safe_filename?: string;
  mime_type?: string;
  byte_size?: number;
  status: "pending" | "uploading" | "ready" | "error" | "deleted";
  error?: string | null;
}

export interface AskAnythingComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** Backward-compatible submit without attachments. Use `onSubmitWithAttachments` for file support. */
  onSubmit?: (value: string) => void;
  /** Called with the message plus any successfully uploaded attachments. */
  onSubmitWithAttachments?: (value: string, attachments: ChatAttachmentSummary[]) => void;
  /** Upload a file and return the persisted attachment summary. */
  onUploadAttachment?: (file: File) => Promise<ChatAttachmentSummary>;
  /** Remove a successfully uploaded attachment from storage. */
  onRemoveAttachment?: (id: number) => Promise<void>;
  /** Called while the assistant is busy to cancel the in-flight request. */
  onCancel?: () => void;
  placeholder?: string;
  ariaLabel?: string;
  submitAriaLabel?: string;
  cancelAriaLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  /** When false the microphone is hidden entirely. */
  voiceEnabled?: boolean;
  /** When true a file picker, paste, and drag-and-drop are shown. */
  attachmentsEnabled?: boolean;
  maxAttachments?: number;
  projectId?: number | string | null;
  className?: string;
}

function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isImage(mimeType?: string): boolean {
  return !!mimeType && mimeType.startsWith("image/");
}

export function AskAnythingComposer({
  value,
  onChange,
  onSubmit,
  onSubmitWithAttachments,
  onUploadAttachment,
  onRemoveAttachment,
  onCancel,
  placeholder = "Ask anything…",
  ariaLabel = "Ask anything",
  submitAriaLabel = "Send",
  cancelAriaLabel = "Stop",
  busy = false,
  disabled = false,
  voiceEnabled = true,
  attachmentsEnabled = false,
  maxAttachments = 10,
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
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const readyAttachments = attachments.filter(
    (a): a is ComposerAttachment & { id: number; status: "ready" } =>
      a.status === "ready" && typeof a.id === "number"
  );

  const canSubmit = value.trim().length > 0 && !busy && !disabled;

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    if (onSubmitWithAttachments) {
      onSubmitWithAttachments(
        value,
        readyAttachments.map((a) => ({
          id: a.id,
          original_filename: a.original_filename,
          safe_filename: a.safe_filename || a.original_filename,
          mime_type: a.mime_type || a.file.type || "application/octet-stream",
          byte_size: a.byte_size ?? a.file.size,
          status: a.status,
        }))
      );
    } else {
      onSubmit?.(value);
    }
    setAttachments((prev) => prev.filter((a) => a.status === "ready"));
  }, [canSubmit, value, readyAttachments, onSubmit, onSubmitWithAttachments]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (canSubmit) handleSubmit();
      }
    },
    [canSubmit, handleSubmit]
  );

  const addAttachments = useCallback(
    (files: FileList | null) => {
      if (!onUploadAttachment || !files) return;
      const availableSlots = Math.max(0, maxAttachments - attachments.length);
      const toUpload = Array.from(files).slice(0, availableSlots);
      toUpload.forEach((file) => {
        const clientId = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        const item: ComposerAttachment = {
          clientId,
          file,
          original_filename: file.name,
          mime_type: file.type,
          byte_size: file.size,
          status: "uploading",
        };
        setAttachments((prev) => [...prev, item]);
        onUploadAttachment(file)
          .then((summary) => {
            setAttachments((prev) =>
              prev.map((a) =>
                a.clientId === clientId
                  ? { ...a, ...summary, status: "ready" }
                  : a
              )
            );
          })
          .catch((err) => {
            setAttachments((prev) =>
              prev.map((a) =>
                a.clientId === clientId
                  ? { ...a, status: "error", error: err instanceof Error ? err.message : "Upload failed" }
                  : a
              )
            );
          });
      });
    },
    [onUploadAttachment, maxAttachments, attachments.length]
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      addAttachments(e.target.files);
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [addAttachments]
  );

  const handleRemove = useCallback(
    async (clientId: string) => {
      const item = attachments.find((a) => a.clientId === clientId);
      if (!item) return;
      if (item.status === "ready" && item.id && onRemoveAttachment) {
        try {
          await onRemoveAttachment(item.id);
        } catch {
          // Best effort; remove from UI anyway.
        }
      }
      setAttachments((prev) => prev.filter((a) => a.clientId !== clientId));
    },
    [attachments, onRemoveAttachment]
  );

  const handleRetry = useCallback(
    (clientId: string) => {
      if (!onUploadAttachment) return;
      const item = attachments.find((a) => a.clientId === clientId);
      if (!item) return;
      setAttachments((prev) =>
        prev.map((a) => (a.clientId === clientId ? { ...a, status: "uploading", error: undefined } : a))
      );
      onUploadAttachment(item.file)
        .then((summary) => {
          setAttachments((prev) =>
            prev.map((a) =>
              a.clientId === clientId ? { ...a, ...summary, status: "ready" } : a
            )
          );
        })
        .catch((err) => {
          setAttachments((prev) =>
            prev.map((a) =>
              a.clientId === clientId
                ? { ...a, status: "error", error: err instanceof Error ? err.message : "Upload failed" }
                : a
            )
          );
        });
    },
    [attachments, onUploadAttachment]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      if (!attachmentsEnabled || !onUploadAttachment) return;
      const files = e.clipboardData?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        addAttachments(files);
      }
    },
    [attachmentsEnabled, onUploadAttachment, addAttachments]
  );

  const handleDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      if (!attachmentsEnabled) return;
      e.preventDefault();
      setIsDragOver(true);
    },
    [attachmentsEnabled]
  );

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      if (!attachmentsEnabled || !onUploadAttachment) return;
      e.preventDefault();
      setIsDragOver(false);
      addAttachments(e.dataTransfer.files);
    },
    [attachmentsEnabled, onUploadAttachment, addAttachments]
  );

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
  const canAddMore = attachments.length < maxAttachments;

  return (
    <div className={cn("w-full", className)}>
      <div
        className={cn(
          "flex flex-col gap-2 rounded-xl border bg-bg-primary px-3 py-2.5 transition-shadow focus-within:ring-2 focus-within:ring-brand-100",
          isRecording
            ? "border-danger ring-2 ring-danger/30"
            : "border-line-secondary",
          isDragOver && attachmentsEnabled && "border-brand bg-brand-50/30 ring-2 ring-brand-100"
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {attachmentsEnabled && attachments.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {attachments.map((att) => (
              <div
                key={att.clientId}
                className={cn(
                  "flex max-w-[200px] items-center gap-2 rounded-lg border px-2 py-1 text-[12px]",
                  att.status === "error"
                    ? "border-danger bg-danger-50 text-danger"
                    : "border-line-tertiary bg-bg-secondary text-ink-secondary"
                )}
              >
                {isImage(att.mime_type) ? (
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-100 text-[10px] text-brand-700">
                    IMG
                  </div>
                ) : (
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-bg-tertiary text-[10px] uppercase text-ink-tertiary">
                    {att.original_filename.split(".").pop()?.slice(0, 3) || "FILE"}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate" title={att.original_filename}>
                    {att.original_filename}
                  </p>
                  <p className="text-[10px] text-ink-tertiary">
                    {att.status === "uploading"
                      ? "Uploading…"
                      : att.status === "error"
                      ? att.error || "Upload failed"
                      : formatBytes(att.byte_size || att.file.size)}
                  </p>
                </div>
                {att.status === "error" ? (
                  <button
                    type="button"
                    onClick={() => handleRetry(att.clientId)}
                    title="Retry upload"
                    className="shrink-0 text-ink-tertiary hover:text-brand-700"
                  >
                    <IconReload size={14} />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleRemove(att.clientId)}
                    title="Remove attachment"
                    disabled={att.status === "uploading"}
                    className="shrink-0 text-ink-tertiary hover:text-danger disabled:opacity-40"
                  >
                    <IconX size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <AutosizeTextarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            minRows={1}
            maxRows={8}
            placeholder={placeholder}
            aria-label={ariaLabel}
            disabled={disabled || busy || isRecording || isProcessing}
            className="min-w-0 flex-1 resize-none bg-transparent text-[14px] text-ink-primary outline-none placeholder:text-ink-tertiary disabled:opacity-60"
          />

          {attachmentsEnabled && canAddMore && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleFileSelect}
                disabled={disabled || busy || isRecording || isProcessing}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled || busy || isRecording || isProcessing}
                title="Attach file"
                aria-label="Attach file"
                className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary transition-colors hover:bg-brand-50 hover:text-brand-700 disabled:opacity-40"
              >
                <IconPlus size={18} />
              </button>
            </>
          )}

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

          {busy && onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              title={cancelAriaLabel}
              aria-label={cancelAriaLabel}
              className="flex h-8 w-8 min-h-touch min-w-touch shrink-0 items-center justify-center rounded-lg bg-danger text-white transition-colors hover:bg-danger/90"
            >
              <IconPlayerStop size={18} />
            </button>
          ) : (
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
          )}
        </div>
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
