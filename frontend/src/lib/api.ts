/** Typed API client with the backend's error envelope, abortable dedupe and debounce.
 *  Assist-only backend: just health, config and the whole-room auto-layout. */

import { API_V1 } from "@/lib/constants";
import type {
  ApiErrorBody,
  AppConfigResponse,
  AssistLayoutOptions,
  HealthResponse,
  PlacedItem,
  Preferences,
  Room,
} from "@/types/api";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(code: string, message: string, status: number, details?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export class NetworkError extends Error {
  constructor(message = "Can't reach the ZORY engine.") {
    super(message);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_V1}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new NetworkError();
  }
  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // non-JSON error body
    }
    const error = body?.error;
    throw new ApiError(
      error?.code ?? "HTTP_ERROR",
      error?.message ?? `Request failed (${response.status})`,
      response.status,
      error?.details,
    );
  }
  return (await response.json()) as T;
}

function post<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(payload) }, signal);
}

/** Keeps only the latest in-flight call per key; older ones are aborted. */
const inflight = new Map<string, AbortController>();

function latest<T>(key: string, run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  inflight.get(key)?.abort();
  const controller = new AbortController();
  inflight.set(key, controller);
  return run(controller.signal).finally(() => {
    if (inflight.get(key) === controller) inflight.delete(key);
  });
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  config: () => request<AppConfigResponse>("/config"),

  /** Whole-room deterministic auto-layout for "Assist with AI". No LLM picks coordinates. */
  assistLayout: (
    room: Room,
    placed_items: PlacedItem[],
    preferences: Preferences,
    opts: { categories?: string[] | null; room_type?: string } = {},
  ) =>
    latest("assist/layout", (s) =>
      post<AssistLayoutOptions>(
        "/assist/layout",
        {
          room,
          placed_items,
          preferences,
          categories: opts.categories ?? null,
          room_type: opts.room_type ?? "living_room",
        },
        s,
      ),
    ),
};

export function debounced<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const wrapped = (...args: A) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped as typeof wrapped & { cancel: () => void };
}
