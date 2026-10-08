const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  code: string;
  status: number;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let message = `Request failed (${res.status})`;
  let extra: Record<string, unknown> = {};
  try {
    const body = await res.json();
    if (body && body.error) {
      const { code: c, message: m, ...rest } = body.error;
      code = c ?? code;
      message = m ?? message;
      extra = rest;
    }
  } catch {
    /* no JSON body */
  }
  return new ApiError(res.status, code, message, extra);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "OFFLINE", "Backend not reachable. Is it running on port 8000?");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: body === undefined ? {} : { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get("content-disposition") ?? "";
  const m = /filename="?([^";]+)"?/.exec(cd);
  return m ? m[1] : fallback;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, json("POST", body)),
  patch: <T>(path: string, body?: unknown) => request<T>(path, json("PATCH", body)),
  del: <T>(path: string) => request<T>(path, json("DELETE")),

  upload<T>(path: string, file: File, fields: Record<string, string> = {}): Promise<T> {
    const fd = new FormData();
    fd.append("file", file, file.name);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    return request<T>(path, { method: "POST", body: fd });
  },

  /** Fetches a file (GET or POST) and hands it to the browser as a download. */
  async download(path: string, body?: unknown, fallbackName = "download"): Promise<string> {
    let res: Response;
    try {
      res = await fetch(BASE + path, body === undefined ? {} : json("POST", body));
    } catch {
      throw new ApiError(0, "OFFLINE", "Backend not reachable.");
    }
    if (!res.ok) throw await parseError(res);
    const blob = await res.blob();
    const name = filenameFrom(res, fallbackName);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    return name;
  },
};
