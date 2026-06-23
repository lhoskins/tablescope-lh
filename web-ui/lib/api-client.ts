export function getApiBaseUrl(): string {
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
    const { protocol, hostname, port } = window.location;
    // Behind the reverse proxy (HTTPS or standard ports), the API is served
    // same-origin and nginx routes /api to the platform API.
    if (protocol === "https:" || port === "" || port === "443" || port === "80") {
      return `${protocol}//${hostname}`;
    }
    // Direct access (e.g. http://host:3000): the API is on :8000 of the host.
    return `${protocol}//${hostname}:8000`;
  }
  // Server-side rendering fallback (containers share a Docker network)
  return "http://localhost:8000";
}

function getApiUrl(): string {
  return getApiBaseUrl();
}

/** Error carrying the HTTP status so callers can branch on 403/404/etc. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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
    throw new ApiError(detail, response.status);
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

/**
 * Open a streaming request (e.g. Server-Sent Events) with the bearer token
 * attached. Returns the raw Response so callers can read `response.body` via a
 * ReadableStream reader — `EventSource` can't set Authorization headers, so we
 * consume SSE over `fetch` instead.
 */
async function streamRequest(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "text/event-stream");
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(`${getApiUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  stream: (path: string, init?: RequestInit) => streamRequest(path, init),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T = void>(path: string) =>
    request<T>(path, { method: "DELETE" }),
  /**
   * Best-effort DELETE that survives page unload (tab close / refresh /
   * navigation). Uses `fetch(..., { keepalive: true })` so the request is
   * dispatched even as the document is being torn down. Fire-and-forget.
   */
  deleteBeacon: (path: string): void => {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    const token = readToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    try {
      void fetch(`${getApiUrl()}${path}`, {
        method: "DELETE",
        headers,
        keepalive: true,
        cache: "no-store",
      });
    } catch {
      /* ignore — best effort */
    }
  },
  upload: <T>(
    path: string,
    file: File,
    fields?: Record<string, string | number | undefined | null>,
  ) => uploadFile<T>(path, file, fields),
  postForm: <T>(path: string, form: FormData) => {
    const headers = new Headers();
    const token = readToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${getApiUrl()}${path}`, {
      method: "POST",
      body: form,
      headers,
    }).then(async (response) => {
      if (!response.ok) {
        let detail = `Request failed: ${response.status}`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail =
              typeof payload.detail === "string"
                ? payload.detail
                : JSON.stringify(payload.detail);
          }
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      return (await response.json()) as T;
    });
  },
};
