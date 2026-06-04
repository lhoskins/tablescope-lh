function resolveApiUrl(): string {
  // Build-time env takes precedence when set to a non-default value
  if (
    typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_API_URL &&
    process.env.NEXT_PUBLIC_API_URL !== "http://localhost:8000"
  ) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  // In the browser, derive the API URL from the current host so the app
  // works on any deployment without hard-coding the IP/domain at build time.
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  // Server-side rendering fallback (containers share a Docker network)
  return "http://localhost:8000";
}

function getApiUrl(): string {
  return resolveApiUrl();
}

const TOKEN_KEY = "tablescope.token";

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${getApiUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        if (typeof payload.detail === "string") {
          detail = payload.detail;
        } else if (Array.isArray(payload.detail)) {
          // Pydantic 422 returns [{loc, msg, ...}, ...]
          detail = payload.detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join("; ");
        } else {
          detail = JSON.stringify(payload.detail);
        }
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function uploadFile<T>(
  path: string,
  file: File,
  fields?: Record<string, string | number | undefined | null>,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (fields) {
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined && value !== null) {
        form.append(key, String(value));
      }
    }
  }
  const headers = new Headers();
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${getApiUrl()}${path}`, {
    method: "POST",
    body: form,
    headers,
  });
  if (!response.ok) {
    let detail = `Upload failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) detail = payload.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T = void>(path: string) =>
    request<T>(path, { method: "DELETE" }),
  upload: <T>(
    path: string,
    file: File,
    fields?: Record<string, string | number | undefined | null>,
  ) => uploadFile<T>(path, file, fields),
};
