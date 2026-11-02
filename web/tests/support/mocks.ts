import fs from "node:fs";

import type { Page, Route } from "@playwright/test";

/**
 * The hosted build (port 4175) asks this site's /api and Tessera for live data. These tests answer both in the
 * browser, so nothing leaves the machine: /api serves the nouns exported with the build, and a fake Tessera
 * keeps requester keys, requests and records in memory, the way the real one answers them.
 */
export const LIVE = `http://localhost:${Number(process.env.ERANOS_TEST_PORT ?? 4174) + 1}`;
export const TESSERA = "https://fabric.teleionlabs.com";

const SNAPSHOT = new URL("../../snapshot/", import.meta.url);

export function snapshot<T = unknown>(path: string): T {
  return JSON.parse(fs.readFileSync(new URL(path, SNAPSHOT), "utf8")) as T;
}

export function noun<T = Record<string, unknown>>(key: string): T {
  return snapshot<{ value: T }>(`nouns/eranos.instructions/${key}.json`).value;
}

export interface SiteMocks {
  plan?: unknown;
  request?: unknown;
  solutions?: Record<string, unknown>;
  fabric?: unknown;
  fabricFails?: boolean;
  /** Public request records fail, as when the site can't be reached. */
  publicFails?: boolean;
  /** Versions of eranos.requests/<id>, each a state change the worker wrote. */
  history?: { version: number; created_at: number; value: unknown }[];
  /** Open tasks as /api/open-tasks lists them. */
  openTasks?: unknown[];
  /** Catalog records by key, as /api/catalog/<key> answers them. */
  catalog?: Record<string, unknown>;
  /** Tracks as /api/tracks answers them; the build's snapshot by default. */
  tracks?: unknown;
  /** Herma's network summary as /api/network answers it; { available: false } (the default) until Herma serves one. */
  network?: Record<string, unknown>;
  /** The shared queue's open Tasks as /api/shared-tasks answers them; unavailable by default. */
  sharedTasks?: Record<string, unknown>;
  /** The models.meta Task Object as /api/models answers it; null (the default) until Tessera holds it. */
  models?: unknown;
}

export async function mockSite(page: Page, mocks: SiteMocks = {}): Promise<string[]> {
  const seen: string[] = [];
  await page.route(`${LIVE}/api/**`, async (route: Route) => {
    const url = new URL(route.request().url());
    const path = decodeURIComponent(url.pathname);
    seen.push(path);
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.startsWith("/api/nouns/eranos.instructions/")) {
      const key = path.split("/").pop() ?? "";
      const file = new URL(`nouns/eranos.instructions/${key}.json`, SNAPSHOT);
      return fs.existsSync(file) ? json(200, JSON.parse(fs.readFileSync(file, "utf8"))) : json(404, { detail: "no such noun" });
    }
    if (mocks.publicFails && /^\/api\/nouns\/eranos\.(plans|requests)\//.test(path)) return json(503, { detail: "unavailable" });
    if (path === "/api/nouns/eranos.solutions") return json(200, { records: [] });
    if (path.startsWith("/api/nouns/eranos.plans/")) return mocks.plan ? json(200, { value: mocks.plan }) : json(404, { detail: "no such noun" });
    if (path.startsWith("/api/nouns/eranos.requests/") && path.endsWith("/history")) {
      return mocks.history ? json(200, { store: "eranos.requests", versions: mocks.history }) : json(404, { detail: "no such noun" });
    }
    if (path === "/api/open-tasks") return mocks.openTasks ? json(200, { tasks: mocks.openTasks }) : json(503, { detail: "unavailable" });
    if (path.startsWith("/api/nouns/eranos.requests/")) return mocks.request ? json(200, { value: mocks.request }) : json(404, { detail: "no such noun" });
    if (path.startsWith("/api/nouns/eranos.solutions/")) {
      const found = mocks.solutions?.[path.split("/").pop() ?? ""];
      return found ? json(200, { value: found }) : json(404, { detail: "no such noun" });
    }
    if (path === "/api/models") return json(200, { store: "eranos.instructions", key: "models.meta", catalog: mocks.models ?? null });
    if (path === "/api/network") return json(200, mocks.network ?? { available: false });
    if (path === "/api/tracks") return json(200, mocks.tracks ?? snapshot("tracks.json"));
    if (path === "/api/shared-tasks") return json(200, mocks.sharedTasks ?? { available: false, tasks: [] });
    if (path === "/api/fabric") {
      if (mocks.fabricFails) return route.abort("failed");
      return json(200, mocks.fabric ?? { queues: ["eq01", "eq02", "eq03"].map((name) => ({ name, ready: 0, leased: 0, waiting: 0, done: 0, dead: 0, cancelled: 0 })) });
    }
    if (path.startsWith("/api/catalog/") && mocks.catalog) {
      const found = mocks.catalog[path.split("/").pop() ?? ""];
      return found ? json(200, found) : json(404, { detail: "no such kit" });
    }
    if (path.startsWith("/api/catalog")) return json(200, snapshot("catalog.json"));
    return json(404, { detail: "no such route" });
  });
  return seen;
}

export interface TesseraCall {
  method: string;
  url: string;
  auth: string | null;
  namespace: string | null;
  body: unknown;
}

/** A fake Tessera with the requester routes the request box and the status page use. */
export class FakeTessera {
  readonly calls: TesseraCall[] = [];
  readonly keys = new Map<string, string>();
  readonly records = new Map<string, { version: number; value: unknown; created_at: number }>();
  readonly tasks = new Map<string, { state: string; created_at: number; brief: unknown }>();
  /** Answers sign-up with this failure instead, such as a 503 with Retry-After. */
  signupFailure: { status: number; code: string; detail: string; retryAfter?: number } | null = null;
  /** Answers the request noun write with this failure. */
  recordFailure: { status: number; detail: string } | null = null;
  events: { seq: number; ts: number; type: string; task_id: string; fencing_token: number | null }[] = [];
  taskState = "ready";

  async install(page: Page): Promise<void> {
    await page.route(`${TESSERA}/**`, (route) => this.answer(route));
  }

  private async answer(route: Route): Promise<void> {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postData() ? JSON.parse(request.postData() ?? "{}") : null;
    const auth = request.headers()["authorization"] ?? null;
    this.calls.push({ method: request.method(), url: request.url(), auth, namespace: request.headers()["x-namespace"] ?? null, body });
    const json = (status: number, data: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(data),
        headers: { "access-control-allow-origin": "*", "access-control-expose-headers": "Retry-After", ...headers },
      });
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    const path = url.pathname;
    if (path === "/v1/session/requester") {
      if (this.signupFailure) {
        const f = this.signupFailure;
        return json(f.status, { detail: f.detail, code: f.code }, f.retryAfter ? { "retry-after": String(f.retryAfter) } : {});
      }
      const key = `tsk_${"ab".repeat(32)}`;
      const principal = `r_${"cd".repeat(16)}`;
      this.keys.set(key, principal);
      return json(201, { key, principal_id: principal, profile: body?.profile });
    }
    const principal = auth?.startsWith("Bearer ") ? this.keys.get(auth.slice(7)) : undefined;
    if (!principal) return json(401, { detail: "a key is required", code: "unauthorized" });
    const parts = path.split("/");
    if (path === "/v1/tasks" && request.method() === "POST") {
      this.tasks.set(body.task_id, { state: this.taskState, created_at: Date.now() / 1000, brief: body.brief });
      this.events = [{ seq: 1, ts: Date.now() / 1000, type: "enqueued", task_id: body.task_id, fencing_token: null }];
      return json(201, { task_id: body.task_id });
    }
    if (parts[2] === "tasks" && request.method() === "GET") {
      const task = this.tasks.get(decodeURIComponent(parts[3] ?? "")) ?? { state: this.taskState, created_at: Date.now() / 1000, brief: {} };
      if (parts[4] === "results") return json(200, { results: [] });
      return json(200, { task_id: parts[3], state: task.state, created_at: task.created_at, updated_at: task.created_at, fencing_token: 0 });
    }
    if (parts[2] === "claims") return json(200, { events: this.events });
    if (parts[2] === "stores") {
      const id = `${principal}/${parts[3]}/${decodeURIComponent(parts[5] ?? "")}`;
      if (request.method() === "GET") {
        const found = this.records.get(id);
        return found ? json(200, { key: parts[5], ...found }) : json(404, { detail: "no such record" });
      }
      if (this.recordFailure) return json(this.recordFailure.status, { detail: this.recordFailure.detail });
      const current = this.records.get(id);
      const version = (current?.version ?? 0) + 1;
      this.records.set(id, { version, value: body.value, created_at: Date.now() / 1000 });
      return json(200, { store: parts[3], key: parts[5], version, created_at: Date.now() / 1000 });
    }
    return json(404, { detail: "no such route" });
  }
}
