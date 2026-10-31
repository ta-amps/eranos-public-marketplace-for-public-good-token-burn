import { FABRIC_PUBLIC_URL } from "../../config";

/**
 * The few Tessera reads a requester key is allowed: the request verb it filed (`task`, `results`, `claimEvents`
 * in the shared namespace) and its own nouns. The key goes only in the Authorization header.
 */

export class TesseraError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "TesseraError";
  }
}

export interface TaskView {
  task_id: string;
  state: string;
  created_at: number;
  updated_at: number;
  fencing_token: number;
}

export interface ClaimEvent {
  seq: number;
  ts: number;
  type: string;
  task_id: string;
  fencing_token: number | null;
}

export interface ResultView {
  ok: boolean;
  output: Record<string, unknown> | null;
  receipt_hash: string;
  created_at: number;
}

export interface RecordView<T> {
  key: string;
  version: number;
  value: T;
  created_at: number;
}

async function call<T>(
  path: string,
  key: string,
  init: { shared?: boolean; method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(FABRIC_PUBLIC_URL + path, {
    method: init.method ?? "GET",
    credentials: "omit",
    cache: "no-store",
    signal: init.signal,
    headers: {
      authorization: `Bearer ${key}`,
      ...(init.shared ? { "x-namespace": "main" } : {}),
      ...(init.body !== undefined ? { "content-type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (!response.ok) {
    let detail = String(response.status);
    let code: string | undefined;
    try {
      const problem = (await response.json()) as { detail?: string; code?: string };
      detail = problem.detail ?? detail;
      code = problem.code;
    } catch {
      // A body that is not JSON keeps the status as its detail.
    }
    const retry = Number(response.headers.get("retry-after"));
    throw new TesseraError(detail, response.status, code, Number.isFinite(retry) && retry > 0 ? retry : undefined);
  }
  return (await response.json()) as T;
}

export function getTask(id: string, key: string, signal?: AbortSignal): Promise<TaskView> {
  return call<TaskView>(`/v1/tasks/${encodeURIComponent(id)}`, key, { shared: true, signal });
}

export async function getClaimEvents(id: string, key: string, after: number, wait = 0, signal?: AbortSignal): Promise<ClaimEvent[]> {
  const query = `?after=${after}${wait ? `&wait=${wait}` : ""}`;
  const out = await call<{ events: ClaimEvent[] }>(`/v1/claims/${encodeURIComponent(id)}/events${query}`, key, { shared: true, signal });
  return out.events ?? [];
}

export async function getResults(id: string, key: string, signal?: AbortSignal): Promise<ResultView[]> {
  const out = await call<{ results: ResultView[] }>(`/v1/tasks/${encodeURIComponent(id)}/results`, key, { shared: true, signal });
  return out.results ?? [];
}

/** A noun in the requester's own namespace, or null when it does not exist. */
export async function getOwnRecord<T>(store: string, recordKey: string, key: string, signal?: AbortSignal): Promise<RecordView<T> | null> {
  try {
    return await call<RecordView<T>>(`/v1/stores/${encodeURIComponent(store)}/records/${encodeURIComponent(recordKey)}`, key, { signal });
  } catch (error) {
    if (error instanceof TesseraError && error.status === 404) return null;
    throw error;
  }
}

/** Writes a new version of a noun in the requester's own namespace; `expectedVersion` 0 creates it. */
export async function putOwnRecord<T>(store: string, recordKey: string, value: T, expectedVersion: number, key: string): Promise<{ version: number; created_at: number }> {
  const out = await call<{ records?: { version: number; created_at: number }[]; version?: number; created_at?: number }>(
    `/v1/stores/${encodeURIComponent(store)}/records/${encodeURIComponent(recordKey)}`,
    key,
    { method: "POST", body: { value, expected_version: expectedVersion } },
  );
  const written = out.records?.[0];
  return { version: Number(written?.version ?? out.version ?? 0), created_at: Number(written?.created_at ?? out.created_at ?? Date.now() / 1000) };
}

/** Files one request verb on `eq01`, the only verb a requester key may file. */
export async function enqueueRequest(taskId: string, brief: Record<string, unknown>, key: string): Promise<void> {
  await call<unknown>("/v1/tasks", key, {
    shared: true,
    method: "POST",
    body: { queue: "eq01", kind: "request", effect_class: "write-internal", task_id: taskId, brief },
  });
}
