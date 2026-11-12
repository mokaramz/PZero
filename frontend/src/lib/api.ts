/**
 * The ONLY way the UI talks to the server.
 *
 * Contract: GET /api/<name>?query and POST /api/<name> with a JSON object body. A path that starts with "/" is used
 * as-is. Failures are JSON `{ ok: false, error: "<operator-readable message>" }` with a non-2xx status; some endpoints
 * also answer `{ error }` with status 200 — `post()` surfaces both as an ApiError so callers handle one path.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Query-string parameters; `undefined`, `null` and `""` are left out of the URL. */
export type Query = Record<string, string | number | boolean | null | undefined>;

export function apiUrl(path: string, query?: Query): string {
  const u = new URL(path.startsWith("/") ? path : `/api/${path}`, window.location.origin);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, String(v));
  }
  return u.pathname + u.search;
}

function errorField(body: unknown): unknown {
  return body && typeof body === "object" && "error" in body ? (body as { error: unknown }).error : undefined;
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    /* non-JSON (e.g. markdown/plain) is returned as a string */
  }
  if (!res.ok) {
    const err = errorField(body);
    throw new ApiError(err !== undefined ? String(err) : `HTTP ${res.status}`, res.status, body);
  }
  return body as T;
}

export async function get<T = unknown>(path: string, query?: Query, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path, query), { credentials: "same-origin", ...init });
  return parse<T>(res);
}

export async function post<T = unknown>(path: string, body: object = {}, opts: { allowErrorField?: boolean } = {}): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await parse<T>(res);
  const err = errorField(data);
  if (!opts.allowErrorField && err) throw new ApiError(String(err), res.status, data);
  return data;
}

/** `attachment; filename="weekly_memo.html"` → `weekly_memo.html` (RFC 5987 `filename*=UTF-8''…` too). */
export function filenameOf(disposition: string | null): string | undefined {
  const m = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return m ? decodeURIComponent(m[1].trim()) : undefined;
}

/** A GET whose answer is a file to save (the Radar HTML): read like every other GET (same-origin credentials, the same
 *  `{error}` failures as an ApiError), then handed to the browser as a download under the server's filename. Resolves
 *  to the saved filename. */
export async function download(path: string, query?: Query, fallbackName = "download"): Promise<string> {
  const res = await fetch(apiUrl(path, query), { credentials: "same-origin" });
  if (!res.ok) await parse(res); // always throws for a non-2xx answer
  const name = filenameOf(res.headers.get("Content-Disposition")) ?? fallbackName;
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000); // after the browser has picked the file up
  return name;
}

/** True when the endpoint does not exist on this server (yet): a view that is not ported stays quiet instead of
 *  showing an error. */
export function isMissingEndpoint(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export const api = { get, post, download };
