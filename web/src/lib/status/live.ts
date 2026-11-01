/**
 * A real request's facts, read from what exists today:
 * - public nouns through this site (`/api/nouns/eranos.plans|requests/<id>`), which need no key;
 * - with the requester key, the request verb it filed (`task`, `claimEvents`, `results`) and its own nouns.
 *
 * What this cannot see yet (written down for the backend, never filled in here):
 * 1. A part's own claim and submit: the requester key may only follow the verb it filed, not its split children,
 *    so a part shows "open" until its check is recorded on the public request noun.
 * 2. Worker labels and declared models: `claimEvents` returns type, time and fencing token only.
 * 3. When a public record changed: `/api/nouns/...` returns the value without its write time.
 */
import { ApiError, getJson } from "../api";
import type { NounResponse } from "../nouns";
import { claimReceipt } from "./ids";
import { getClaimEvents, getOwnRecord, getResults, getTask, type ClaimEvent, type ResultView, type TaskView } from "./tessera";
import type { DecisionChoice, Frequency, OutputType, PartPlan, QueueSnapshot, StatusEvent, StatusRecord } from "./types";

interface PlanNounValue {
  request_id: string;
  receipt?: { task_id?: string; claim_receipt?: string };
  parts?: PartPlan[];
  plain?: string[];
  findings?: string[];
  closed?: { receipt?: string };
}

interface RequestPart {
  route?: string;
  status?: string;
  findings?: string[];
  notes?: string;
  review_receipt?: string;
  solution?: { store?: string; key?: string; version?: number };
  kit_id?: string;
  catalog_version?: number;
}

interface RequestNounValue {
  request_id: string;
  status?: string;
  output_type?: OutputType;
  frequency?: Frequency;
  text?: string | null;
  findings?: string[];
  parts?: Record<string, RequestPart>;
  close_receipt?: string;
}

export interface OwnRequestValue {
  text?: string;
  links?: string[];
  organization_type?: string;
  output_type?: OutputType;
  frequency?: Frequency;
}

/** The nonprofit's decisions on each part, a noun in its own namespace (`org.decisions/<request_id>`). */
export interface DecisionsValue {
  schema_version: 1;
  request_id: string;
  parts: Record<string, { choice: DecisionChoice; decided_at: number; note?: string }>;
}

export const DECISIONS_STORE = "org.decisions";

/** What the requester key can read: the request verb it filed, its claim events and results, its own nouns. */
export interface KeyedData {
  task: TaskView;
  events: ClaimEvent[];
  cursor: number;
  results: ResultView[];
  own: OwnRequestValue | null;
  decisions: { version: number; value: DecisionsValue } | null;
}

export interface LiveSnapshot {
  record: StatusRecord;
  /** Nothing about this request is visible: no public noun, and no key or no verb. */
  missing: boolean;
  decisions: KeyedData["decisions"];
}

async function publicNoun<T>(store: string, id: string): Promise<T | null> {
  try {
    const found = await getJson<NounResponse<T>>(`/api/nouns/${store}/${encodeURIComponent(id)}`);
    return found.value;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** The request's first sentence as its title, cut at a word boundary when it is long. */
export function firstSentence(text: string): string {
  const sentence = text.trim().split(/(?<=[.!?])\s+|\n+/)[0] ?? "";
  const plain = sentence.replace(/[.!?]+$/, "");
  if (plain.length <= 110) return plain;
  const cut = plain.slice(0, 108);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 60)).replace(/[,;:]$/, "")}…`;
}

/**
 * One read with the requester key. Claim events are read every time (a long poll of up to `wait` seconds, only
 * newer events); the task, its results and the key's own nouns only on a full read. That keeps one page within
 * the key's 300 requests an hour.
 */
export async function readKeyed(id: string, key: string, previous: KeyedData | null, full = true, wait = 0): Promise<KeyedData> {
  if (!full && previous) {
    const fresh = await getClaimEvents(id, key, previous.cursor, wait);
    if (!fresh.length) return previous;
    const events = [...previous.events, ...fresh];
    const results = fresh.some((e) => e.type === "submitted") ? await getResults(id, key) : previous.results;
    return { ...previous, events, results, cursor: Math.max(previous.cursor, ...fresh.map((e) => e.seq)) };
  }
  const task = await getTask(id, key);
  const cursor = previous?.cursor ?? 0;
  const fresh = await getClaimEvents(id, key, cursor);
  const events = [...(previous?.events ?? []), ...fresh];
  const next = fresh.length ? Math.max(cursor, ...fresh.map((e) => e.seq)) : cursor;
  const results = events.some((e) => e.type === "submitted") ? await getResults(id, key) : (previous?.results ?? []);
  const [own, decided] = await Promise.all([
    previous?.own ? Promise.resolve({ value: previous.own }) : getOwnRecord<OwnRequestValue>("org.requests", id, key),
    getOwnRecord<DecisionsValue>(DECISIONS_STORE, id, key),
  ]);
  return {
    task,
    events,
    cursor: next,
    results,
    own: own?.value ?? null,
    decisions: decided ? { version: decided.version, value: decided.value } : null,
  };
}

/**
 * The live workers' other names for facts the page already knows (both are accepted): `added` is `library_added`;
 * `reused` is a part delivered or published from the library with no new work; `scheduled` is a recurring
 * request's next run (`queued` with `summary.next_at`); `work_failed` is a failed try that went back in line
 * (`work_released` with its reason).
 */
export function canonicalEvent(event: StatusEvent): StatusEvent {
  const raw = event as Omit<StatusEvent, "type"> & { type: string; next_at?: number };
  switch (raw.type as string) {
    case "added":
      return { ...event, type: "library_added" };
    case "reused": {
      const kit = /^(KIT|PRC)-/.test(event.result_id ?? "");
      return { ...event, type: kit ? "published" : "delivered", summary: { ...event.summary, reused: true } };
    }
    case "scheduled":
      return { ...event, type: "queued", summary: { ...event.summary, next_at: event.summary?.next_at ?? raw.next_at } };
    case "work_failed":
      return { ...event, type: "work_released", reason: event.reason || "the try failed" };
    default:
      return event;
  }
}

interface HistoryVersion {
  version: number;
  created_at: number;
  value: RequestNounValue & { event?: StatusEvent };
}

/** The request record's public versions, each a state change the worker wrote with its receipt, or null. */
async function requestHistory(id: string): Promise<HistoryVersion[] | null> {
  try {
    const found = await getJson<{ versions: HistoryVersion[] }>(`/api/nouns/eranos.requests/${encodeURIComponent(id)}/history`);
    return found.versions ?? null;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 502)) return null;
    throw error;
  }
}

/** Everything this page may see about a request: the public nouns, plus the keyed read when there is one. */
export async function readLive(id: string, keyed: KeyedData | null): Promise<LiveSnapshot> {
  const [plan, request, history] = await Promise.all([
    publicNoun<PlanNounValue>("eranos.plans", id),
    publicNoun<RequestNounValue>("eranos.requests", id),
    requestHistory(id),
  ]);
  const task = keyed?.task ?? null;
  const claimEvents = keyed?.events ?? [];
  const results = keyed?.results ?? [];
  const own = keyed?.own ?? null;
  const decisions = keyed?.decisions ?? null;

  const events: StatusEvent[] = [];
  const enqueued = claimEvents.find((e) => e.type === "enqueued");
  const sentAt = enqueued?.ts ?? task?.created_at ?? null;
  if (task || plan || request) events.push({ type: "received", at: sentAt, ref: id });

  // The request verb's own claims, until it is planned: each claim's receipt is Tessera's formula on the event.
  const split = claimEvents.find((e) => e.type === "split");
  for (const e of claimEvents) {
    if (split && e.seq > split.seq) break;
    if (e.type === "claimed" && e.fencing_token !== null) {
      events.push({ type: "plan_claimed", at: e.ts, receipt: await claimReceipt("main", id, e.fencing_token, e.ts) });
    } else if (e.type === "lease_lapsed" || e.type === "retry_scheduled") {
      events.push({ type: "plan_released", at: e.ts, ref: `${id} event ${e.seq}` });
    } else if (e.type === "heartbeat") {
      events.push({ type: "heartbeat", at: e.ts, ref: `${id} event ${e.seq}` });
    }
  }

  const blockedResult = results.find((r) => r.output && (r.output as { status?: string }).status === "blocked");
  const findings = plan?.findings ?? request?.findings ?? [];
  if ((plan && findings.length && !(plan.parts ?? []).length) || request?.status === "blocked") {
    events.push({
      type: "blocked",
      at: blockedResult?.created_at ?? null,
      receipt: blockedResult?.receipt_hash ?? plan?.receipt?.claim_receipt,
      ref: `eranos.plans/${id}`,
      findings,
    });
  } else if (plan && (plan.parts ?? []).length) {
    events.push({
      type: "planned",
      at: split?.ts ?? null,
      receipt: plan.receipt?.claim_receipt,
      ref: `eranos.plans/${id}`,
      parts: plan.parts,
    });
    for (const part of plan.parts ?? []) {
      const n = part.part;
      const state = request?.parts?.[String(n)];
      const ref = `eranos.requests/${id} part ${n}`;
      switch (state?.status) {
        case "in_review":
          events.push({ type: "in_review", part: n, at: null, ref });
          break;
        case "needs_revision":
          events.push({
            type: "check_sent_back",
            part: n,
            at: null,
            ref,
            reason: (state.findings ?? []).join("; ") || state.notes || undefined,
          });
          break;
        case "awaiting_steward":
          events.push({ type: "check_approved", part: n, at: null, ref });
          events.push({ type: "signoff_required", part: n, at: null, ref });
          break;
        case "delivered":
          events.push({ type: "check_approved", part: n, at: null, receipt: state.review_receipt, ref });
          events.push({
            type: "delivered",
            part: n,
            at: null,
            receipt: state.review_receipt,
            ref: `eranos.solutions/${state.solution?.key ?? part.report_id ?? ""}`,
            result_id: state.solution?.key ?? part.report_id,
          });
          break;
        case "published":
          events.push({ type: "check_approved", part: n, at: null, ref });
          events.push({
            type: "published",
            part: n,
            at: null,
            ref: `eranos.catalog/${state.kit_id ?? part.kit_id ?? ""} version ${state.catalog_version ?? ""}`.trim(),
            result_id: state.kit_id ?? part.kit_id,
          });
          break;
      }
      const decision = decisions?.value.parts?.[String(n)];
      if (decision) {
        events.push({
          type: "decided",
          part: n,
          at: decision.decided_at,
          choice: decision.choice,
          ref: `${DECISIONS_STORE}/${id} version ${decisions?.version ?? ""}`,
        });
      }
    }
  }
  // When the worker writes each state change as a version that cites its receipt, those versions are the facts.
  const written = (history ?? []).filter((v) => v.value?.event && (v.value.event.receipt || v.value.event.ref));
  if (written.length) {
    const base = `/api/nouns/eranos.requests/${encodeURIComponent(id)}/history`;
    const own = events.filter((e) => e.type === "received" || e.type === "plan_claimed" || e.type === "decided");
    events.length = 0;
    const fromHistory = written.map((v) => ({ ...canonicalEvent(v.value.event as StatusEvent), record: `${base}#v${v.version}` }));
    if (!fromHistory.some((e) => e.type === "received")) events.push(...own.filter((e) => e.type === "received"));
    events.push(...fromHistory);
    for (const e of own) if (e.type === "decided" && !fromHistory.some((h) => h.type === "decided" && h.part === e.part)) events.push(e);
  } else {
    for (const e of events) {
      if (e.record) continue;
      if (e.type === "planned" || e.type === "blocked") e.record = `/api/nouns/eranos.plans/${encodeURIComponent(id)}`;
      else if (e.ref?.startsWith("eranos.requests/")) e.record = `/api/nouns/eranos.requests/${encodeURIComponent(id)}`;
      else if (e.ref?.startsWith("eranos.solutions/")) e.record = `/api/nouns/${e.ref.split(" ")[0]}`;
      else if (e.ref?.startsWith("eranos.catalog/") && e.result_id) e.record = `/api/catalog/${encodeURIComponent(e.result_id)}`;
    }
  }
  const closeReceipt = request?.close_receipt ?? plan?.closed?.receipt;
  if (request?.status === "closed" && closeReceipt) events.push({ type: "closed", at: null, receipt: closeReceipt });
  if (task?.state === "cancelled") events.push({ type: "withdrawn", at: task.updated_at, ref: `${id} cancelled` });

  const text = request ? (request.text ?? null) : (own?.text ?? null);
  const record: StatusRecord = {
    mode: "live",
    request: {
      id,
      title: text ? firstSentence(text) : own?.text ? firstSentence(own.text) : undefined,
      text: request && request.text === null && own?.text ? own.text : text,
      organization_type: own?.organization_type,
      output_type: own?.output_type ?? request?.output_type,
      frequency: own?.frequency ?? request?.frequency,
      cadence: (own as { cadence?: string } | undefined)?.cadence ?? (request as { cadence?: string } | null | undefined)?.cadence,
      sent_at: sentAt,
    },
    events,
    estimate: null,
  };
  return { record, missing: !task && !plan && !request, decisions };
}

/** Eranos's queues from `/api/fabric`: waiting is every ready task, checking is a leased review. */
export function queueFromFabric(queues: { name: string; ready: number; leased: number }[]): QueueSnapshot | null {
  if (!queues.length) return null;
  const by = new Map(queues.map((q) => [q.name, q]));
  const ready = (name: string) => by.get(name)?.ready ?? 0;
  const leased = (name: string) => by.get(name)?.leased ?? 0;
  return {
    waiting: ready("eq01") + ready("eq02") + ready("eq03"),
    working: leased("eq01") + leased("eq02"),
    checking: leased("eq03"),
    agents: [],
  };
}
