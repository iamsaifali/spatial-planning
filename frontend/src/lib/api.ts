/** Typed API client with the backend's error envelope, abortable dedupe and debounce. */

import { API_V1 } from "@/lib/constants";
import type {
  AnalysisResponse,
  ApiErrorBody,
  AppConfigResponse,
  AssistantResponse,
  DesignCreateResponse,
  DesignResponse,
  HealthResponse,
  MajlisGenerateResponse,
  OrderResponse,
  PlacedItem,
  PlanResponse,
  Preferences,
  ProductListResponse,
  RenderResponse,
  Room,
  RoomValidateResponse,
  StepResponse,
  StepsResponse,
  SuggestResponse,
  SummaryResponse,
  ValidateResponse,
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

  validateRoom: (room: Room) =>
    latest("rooms/validate", (s) => post<RoomValidateResponse>("/rooms/validate", { room }, s)),

  analyzeRoom: (room: Room) =>
    latest("rooms/analyze", (s) => post<AnalysisResponse>("/rooms/analyze", { room }, s)),

  guideSteps: (room: Room, placed_items: PlacedItem[]) =>
    post<StepsResponse>("/guide/steps", { room, placed_items }),

  guideStep: (stepKey: string, room: Room, preferences: Preferences, placed_items: PlacedItem[]) =>
    latest(`guide/${stepKey}`, (s) =>
      post<StepResponse>(`/guide/step/${stepKey}`, { room, preferences, placed_items }, s),
    ),

  plan: (room: Room, preferences: Preferences, placed_items: PlacedItem[]) =>
    latest("guide/plan", (s) => post<PlanResponse>("/guide/plan", { room, preferences, placed_items }, s)),

  majlisGenerate: (room: Room, preferences: Preferences) =>
    latest("majlis/generate", (s) => post<MajlisGenerateResponse>("/majlis/generate", { room, preferences }, s)),

  suggestPlacement: (
    room: Room,
    placed_items: PlacedItem[],
    product_id: string,
    zone_id?: string | null,
    preferences?: Preferences,
  ) => post<SuggestResponse>("/placement/suggest", { room, placed_items, product_id, zone_id, preferences }),

  validatePlacement: (room: Room, placed_items: PlacedItem[], item: PlacedItem, preferences: Preferences) =>
    latest(`validate/${item.instance_id}`, (s) =>
      post<ValidateResponse>("/placement/validate", { room, placed_items, item, preferences }, s),
    ),

  products: (params: Record<string, string | number | boolean | undefined>) => {
    const query = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return request<ProductListResponse>(`/products${query ? `?${query}` : ""}`);
  },

  summary: (room: Room, placed_items: PlacedItem[], preferences: Preferences, currency?: string) =>
    post<SummaryResponse>("/summary", { room, placed_items, preferences, currency }),

  render: (
    room: Room,
    placed_items: PlacedItem[],
    preferences: Preferences,
    canvas_png_b64: string,
    signal?: AbortSignal,
  ) => post<RenderResponse>("/render", { room, placed_items, preferences, canvas_png_b64 }, signal),

  ask: (question: string, room: Room, placed_items: PlacedItem[], preferences: Preferences, step_key?: string) =>
    post<AssistantResponse>("/assistant/ask", { question, room, placed_items, preferences, step_key }),

  saveDesign: (name: string | null, room: Room, placed_items: PlacedItem[], preferences: Preferences) =>
    post<DesignCreateResponse>("/designs", { name, room, placed_items, preferences }),

  getDesign: (id: string) => request<DesignResponse>(`/designs/${encodeURIComponent(id)}`),

  checkout: (
    items: { product_id: string; qty: number }[],
    contact: { name: string; email: string },
    currency?: string,
  ) => post<OrderResponse>("/checkout", { items, contact, currency }),
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
