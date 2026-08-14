import { getApiBaseUrl } from "@/lib/api-client";

const TOKEN_KEY = "tablescope.token";

export interface TranscribeResponse {
  transcript: string;
  duration_ms?: number;
}

export async function transcribeAudio(
  blob: Blob,
  mimeType: string,
  projectId?: number | string | null,
): Promise<TranscribeResponse> {
  if (typeof window === "undefined") {
    throw new Error("transcribeAudio must be called in the browser");
  }

  const token = window.localStorage.getItem(TOKEN_KEY);
  const form = new FormData();
  form.append("audio", blob, `recording.${mimeType.includes("mp4") ? "m4a" : "webm"}`);
  form.append("mime_type", mimeType);
  if (projectId != null) {
    form.append("project_id", String(projectId));
  }

  const res = await fetch(`${getApiBaseUrl()}/api/ai/speech/transcribe`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: "Transcription failed" }));
    throw new Error(body.message || "Transcription failed");
  }

  return (await res.json()) as TranscribeResponse;
}
