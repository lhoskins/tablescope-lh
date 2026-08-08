"use client";

import { useCallback, useRef, useState } from "react";

export type VoiceRecorderState =
  | "idle"
  | "requesting"
  | "recording"
  | "processing"
  | "unsupported"
  | "denied"
  | "no_speech"
  | "unavailable";

export interface VoiceRecorderResult {
  blob: Blob;
  mimeType: string;
  durationMs: number;
}

interface UseVoiceRecorderReturn {
  state: VoiceRecorderState;
  error: string | null;
  durationMs: number;
  start: () => Promise<void>;
  stop: () => Promise<VoiceRecorderResult | null>;
  cancel: () => void;
}

const PREFERRED_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/mp4;codecs=mp4a.40.2",
];

function selectMimeType(): string | null {
  if (typeof window === "undefined" || !window.MediaRecorder) return null;
  for (const t of PREFERRED_TYPES) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return null;
}

export function useVoiceRecorder(): UseVoiceRecorderReturn {
  const [state, setState] = useState<VoiceRecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const durationRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedMimeTypeRef = useRef<string | null>(null);

  const cleanupTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    cleanupTracks();
    clearTimer();
    recorderRef.current = null;
    chunksRef.current = [];
    durationRef.current = 0;
    setDurationMs(0);
    setError(null);
  }, [cleanupTracks, clearTimer]);

  const start = useCallback(async () => {
    reset();
    const mimeType = selectMimeType();
    if (!mimeType) {
      setState("unsupported");
      return;
    }
    selectedMimeTypeRef.current = mimeType;
    setState("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onerror = () => {
        setState("unavailable");
        cleanupTracks();
        clearTimer();
      };

      recorder.onstop = () => {
        cleanupTracks();
        clearTimer();
      };

      recorder.start(200);
      startedAtRef.current = Date.now();
      durationRef.current = 0;
      setDurationMs(0);
      setState("recording");
      timerRef.current = setInterval(() => {
        durationRef.current = Date.now() - startedAtRef.current;
        setDurationMs(durationRef.current);
      }, 100);
    } catch (err) {
      cleanupTracks();
      if (err instanceof DOMException) {
        if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
          setState("denied");
        } else if (err.name === "NotFoundError") {
          setState("unsupported");
        } else {
          setState("unavailable");
        }
      } else {
        setState("unavailable");
      }
    }
  }, [reset, cleanupTracks, clearTimer]);

  const stop = useCallback(async (): Promise<VoiceRecorderResult | null> => {
    const recorder = recorderRef.current;
    if (!recorder || state !== "recording") return null;
    return new Promise((resolve) => {
      recorder.onstop = () => {
        cleanupTracks();
        clearTimer();
        const blob = new Blob(chunksRef.current, {
          type: selectedMimeTypeRef.current || "audio/webm",
        });
        const result: VoiceRecorderResult = {
          blob,
          mimeType: selectedMimeTypeRef.current || "audio/webm",
          durationMs: durationRef.current,
        };
        resolve(result);
      };
      recorder.stop();
    });
  }, [state, cleanupTracks, clearTimer]);

  const cancel = useCallback(() => {
    try {
      recorderRef.current?.stop();
    } catch {
      /* ignore */
    }
    reset();
    setState("idle");
  }, [reset]);

  return { state, error, durationMs, start, stop, cancel };
}
