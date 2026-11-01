/**
 * Facts in, picture out. `applyEvents` folds the recorded facts into each step's state, and `deriveView` turns
 * that into the diagram's nodes, edges and chips, the list view, the log, the live summary and the tab title.
 * A step changes state only when a fact with a receipt or a record reference says so.
 *
 * Receipt or record -> node state (the diagram reads request -> plan -> queue -> worker -> review -> result):
 * | fact                   | node change                                                              |
 * |------------------------|--------------------------------------------------------------------------|
 * | received               | Your request: noun (always present)                                      |
 * | plan_claimed           | Plan: working, with the agent's chip and lease                            |
 * | planned                | Plan: done; one row per part appears, its queue step waiting             |
 * | blocked                | Plan: stopped; nothing else starts                                        |
 * | plan_released          | Plan: waiting again                                                       |
 * | work_claimed           | Queue: picked up; Worker: "A worker is now working on this", with a chip  |
 * | work_released          | Queue: waiting again, in line; Worker: not started                        |
 * | work_submitted         | Worker: draft ready (its receipt)                                         |
 * | check_claimed          | Review: working, with a different agent's chip                            |
 * | in_review              | Review: working (the public request record says so)                       |
 * | check_approved         | Review: approved                                                          |
 * | check_sent_back        | Review: sent back; the part returns to the queue                          |
 * | signoff_required       | Result: a person signs off                                                |
 * | delivered / published  | Result: your turn                                                         |
 * | decided                | Result: decided ("You used it"), with its record                          |
 * | closed                 | the request is finished                                                   |
 * | withdrawn              | open steps stop; finished parts stay                                      |
 *
 * In live mode a part's queue step starts as "open": Tessera doesn't yet share a part's claim with the requester's
 * key, so the page says what the public record says, that the part is open to volunteers' agents.
 */
import { fill, type RequestStatusNoun } from "../nouns";
import { ordinal, placeLine, pickupEstimate, type PickupEstimate } from "./estimate";
import { shortReceipt, shortRequestId } from "./ids";
import type { DecisionChoice, PartPlan, QueueSnapshot, StatusEvent, StatusRecord } from "./types";

export type NodeState =
  | "noun"
  | "idle"
  | "waiting"
  | "open"
  | "working"
  | "done"
  | "approved"
  | "sent_back"
  | "person"
  | "yourturn"
  | "decided"
  | "stopped"
  | "held";

interface Agent {
  who?: string;
  /** One of Eranos's own workers (the fallback when no volunteer is free), not a volunteer's agent. */
  dedicated?: boolean;
  model?: string;
  claimedAt?: number | null;
  leaseEnds?: number;
  receipt?: string;
}

interface Evidence {
  receipt?: string;
  ref?: string;
  at?: number | null;
}

interface PartFacts {
  plan: PartPlan;
  work: "idle" | "waiting" | "open" | "working" | "done" | "held";
  workAgent?: Agent;
  submitted?: Evidence & { who?: string; sources?: number };
  place?: number;
  check: "idle" | "open" | "working" | "approved" | "sent_back";
  checkAgent?: Agent;
  checkEvidence?: Evidence & { who?: string; reason?: string };
  decide: "idle" | "person" | "yourturn" | "decided";
  decideEvidence?: Evidence;
  decision?: Evidence & { choice: DecisionChoice };
  result: "idle" | "noun";
  resultEvidence?: Evidence & { id?: string };
  released?: Evidence & { who?: string; reason?: string };
  library?: Evidence & { id?: string };
}

export interface Facts {
  received?: Evidence;
  plan: "waiting" | "working" | "done" | "stopped";
  planAgent?: Agent;
  planEvidence?: Evidence & { who?: string };
  planPlace?: number;
  blocked?: Evidence & { findings: string[] };
  parts: PartFacts[];
  closed?: Evidence;
  withdrawn?: Evidence;
  queue?: QueueSnapshot;
  heartbeats: number;
}

function evidence(event: StatusEvent): Evidence {
  return { receipt: event.receipt, ref: event.ref, at: event.at ?? null };
}

function agent(event: StatusEvent): Agent {
  return {
    who: event.worker,
    dedicated: event.dedicated ?? /^eranos[-_.\s]/i.test(event.worker ?? ""),
    // The model id the fact declares; its display name comes from the models.meta Task Object (lib/models.ts).
    model: event.model,
    claimedAt: event.at ?? null,
    leaseEnds: event.lease_ends,
    receipt: event.receipt,
  };
}

function hasEvidence(event: StatusEvent): boolean {
  return Boolean(event.receipt || event.ref);
}

/** Folds the facts, in order, into each step's state. A fact without a receipt or a record is ignored. */
export function applyEvents(events: StatusEvent[], live = false): Facts {
  const facts: Facts = { plan: "waiting", parts: [], heartbeats: 0 };
  const part = (n: number | undefined) => facts.parts.find((p) => p.plan.part === n);
  for (const event of events) {
    if (event.queue) facts.queue = event.queue;
    if (event.type === "heartbeat") {
      facts.heartbeats += 1;
      continue;
    }
    if (!hasEvidence(event)) continue;
    if (event.places) {
      for (const [n, place] of Object.entries(event.places)) {
        const p = part(Number(n));
        if (p) p.place = place;
      }
    }
    switch (event.type) {
      case "received":
        facts.received = evidence(event);
        if (event.place) facts.planPlace = event.place;
        break;
      case "queued":
        if (event.place) facts.planPlace = event.place;
        break;
      case "library_added": {
        const p = part(event.part);
        if (p) p.library = { ...evidence(event), ref: event.library_ref ?? event.ref, id: event.result_id };
        break;
      }
      case "plan_claimed":
        if (facts.plan !== "done") {
          facts.plan = "working";
          facts.planAgent = agent(event);
        }
        break;
      case "plan_released":
        if (facts.plan !== "done") {
          facts.plan = "waiting";
          facts.planAgent = undefined;
          if (event.place) facts.planPlace = event.place;
        }
        break;
      case "planned":
        facts.plan = "done";
        facts.planEvidence = { ...evidence(event), who: event.worker ?? facts.planAgent?.who };
        facts.planAgent = undefined;
        facts.parts = (event.parts ?? []).map((plan) => ({
          plan,
          work: plan.route === "held" ? "held" : live ? "open" : "waiting",
          check: live && plan.route !== "held" ? "open" : "idle",
          decide: "idle",
          result: "idle",
        }));
        if (event.places) {
          for (const [n, place] of Object.entries(event.places)) {
            const p = part(Number(n));
            if (p) p.place = place;
          }
        }
        break;
      case "blocked":
        facts.plan = "stopped";
        facts.planAgent = undefined;
        facts.blocked = { ...evidence(event), findings: event.findings ?? (event.reason ? [event.reason] : []) };
        break;
      case "work_claimed": {
        const p = part(event.part);
        if (!p) break;
        p.work = "working";
        p.workAgent = agent(event);
        p.released = undefined;
        break;
      }
      case "work_released": {
        const p = part(event.part);
        if (!p) break;
        p.released = { ...evidence(event), who: event.worker ?? p.workAgent?.who, reason: event.reason };
        p.work = live ? "open" : "waiting";
        p.workAgent = undefined;
        break;
      }
      case "work_submitted": {
        const p = part(event.part);
        if (!p) break;
        p.work = "done";
        p.submitted = { ...evidence(event), who: event.worker ?? p.workAgent?.who, sources: event.summary?.sources };
        p.workAgent = undefined;
        p.result = "noun";
        p.resultEvidence = { ...evidence(event) };
        if (p.check === "open") p.check = "idle";
        break;
      }
      case "check_claimed": {
        const p = part(event.part);
        if (!p) break;
        p.check = "working";
        p.checkAgent = agent(event);
        break;
      }
      case "in_review": {
        const p = part(event.part);
        if (!p) break;
        if (p.work === "open") p.work = "done";
        p.check = "working";
        p.checkEvidence = { ...evidence(event) };
        break;
      }
      case "check_approved": {
        const p = part(event.part);
        if (!p) break;
        if (p.work === "open" || p.work === "waiting") p.work = "done";
        p.check = "approved";
        p.checkEvidence = { ...evidence(event), who: event.worker ?? p.checkAgent?.who };
        p.checkAgent = undefined;
        break;
      }
      case "check_sent_back": {
        const p = part(event.part);
        if (!p) break;
        p.check = "sent_back";
        p.checkEvidence = { ...evidence(event), who: event.worker ?? p.checkAgent?.who, reason: event.reason };
        p.checkAgent = undefined;
        p.work = live ? "open" : "waiting";
        p.result = "idle";
        break;
      }
      case "signoff_required": {
        const p = part(event.part);
        if (!p) break;
        p.decide = "person";
        p.decideEvidence = evidence(event);
        break;
      }
      case "signed_off": {
        const p = part(event.part);
        if (!p) break;
        p.decideEvidence = evidence(event);
        break;
      }
      case "delivered":
      case "published": {
        const p = part(event.part);
        if (!p) break;
        if (p.work !== "done") p.work = "done";
        if (p.check !== "approved") p.check = "approved";
        p.result = "noun";
        p.resultEvidence = { ...evidence(event), id: event.result_id };
        if (p.decide !== "decided") {
          p.decide = "yourturn";
          p.decideEvidence = evidence(event);
        }
        break;
      }
      case "decided": {
        const p = part(event.part);
        if (!p || !event.choice) break;
        p.decide = "decided";
        p.decision = { ...evidence(event), choice: event.choice };
        break;
      }
      case "closed":
        facts.closed = evidence(event);
        if (facts.parts.length > 0) {
          facts.plan = "done";
          facts.planAgent = undefined;
        }
        break;
      case "withdrawn":
        facts.withdrawn = evidence(event);
        break;
    }
  }
  return facts;
}

/* ---------------------------------------------------------------- the picture */

export interface NodeView {
  id: string;
  kind: "request" | "plan" | "queue" | "worker" | "review" | "result";
  part?: number;
  state: NodeState;
  label: string;
  sub?: string;
  /** The receipt hash or record reference behind the state; empty only for idle steps. */
  evidence?: string;
  /** The public address where that receipt or record can be read. */
  record?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  r: number;
}

export interface ChipView {
  id: string;
  node: string;
  x: number;
  y: number;
  text: string;
  kind: "agent" | "plain" | "link";
  href?: string;
  lease?: { start: number; end: number };
}

export interface EdgeView {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  head: boolean;
  done: boolean;
  /** The node the edge leads to, for the dot that travels it when a step finishes. */
  to?: string;
}

export interface LogRow {
  key: string;
  at: number | null;
  text: string;
  evidence?: string;
}

export interface StepView {
  key: string;
  label: string;
  state: NodeState;
  word: string;
  detail?: string;
  evidence?: string;
  href?: string;
  action?: string;
}

export interface PartCardView {
  part: number;
  route: PartPlan["route"];
  title: string;
  subtitle: string;
  steps: StepView[];
  note?: string;
}

export type Tone = "waiting" | "verb" | "attention" | "real" | "caution" | "noun";

export interface StatusView {
  id: string;
  shortId: string;
  title: string;
  overall: { label: string; tone: Tone };
  nodes: NodeView[];
  edges: EdgeView[];
  chips: ChipView[];
  labels: { id: string; x: number; y: number; text: string }[];
  height: number;
  planned: boolean;
  log: LogRow[];
  parts: PartCardView[];
  planCard: StepView;
  summary: string;
  docTitle: string;
  yourTurnPart?: number;
  queue?: QueueSnapshot;
  estimate: PickupEstimate | null;
  facts: Facts;
}

export interface DeriveOptions {
  /** Unix seconds, for the pick-up estimate. */
  now: number;
  formatTime: (at: number) => string;
  formatClock: (at: number) => string;
  /** The page that shows a part's result: its cited report or its reusable process. */
  resultHref: (part: number) => string;
  /** The display name of a declared model, from the models.meta Task Object; without it no model is named. */
  modelName?: (id: string | undefined, dedicated: boolean) => string | null;
}

const COL = {
  request: { x: 0, w: 140, h: 56, r: 12 },
  plan: { x: 175, w: 110, h: 44, r: 22 },
  queue: { x: 320, w: 130, h: 44, r: 22 },
  worker: { x: 530, w: 190, h: 56, r: 16 },
  review: { x: 760, w: 150, h: 44, r: 22 },
  result: { x: 950, w: 170, h: 56, r: 12 },
} as const;
const ROW = 150;
const FIRST_ROW = 70;
const FORK_X = 302;

function rowCenter(index: number): number {
  return FIRST_ROW + index * ROW;
}

function evidenceOf(e: { receipt?: string; ref?: string } | undefined): string | undefined {
  return e?.receipt ?? e?.ref;
}

/** How the details name a worker: "dedicated worker N (run by ta-amps)" for Eranos's own, else the label it reports. */
export function workerLabel(words: RequestStatusNoun, who: string | undefined, dedicated?: boolean): string | undefined {
  if (!who) return who;
  const own = dedicated ?? /^eranos[-_.\s]/i.test(who);
  // N is the worker's own number, without a host's leading zeros ("eranos-review-pc02" is worker 2).
  const digits = /(\d+)/.exec(who)?.[1];
  return own ? fill(words.chips.dedicated ?? "", { n: digits ? String(Number(digits)) : "1" }) : who;
}

function agentChipText(words: RequestStatusNoun, a: Agent, options: DeriveOptions): string {
  // A dedicated worker is named as the owner asked: "dedicated worker N (run by ta-amps)", with its model through
  // the Meta API; a volunteer's chip names the model it declared. Names come from the models.meta Task Object.
  const who = workerLabel(words, a.who, a.dedicated) ?? (a.dedicated ? fill(words.chips.dedicated ?? "", { n: "1" }) : undefined);
  const model = options.modelName ? options.modelName(a.model, Boolean(a.dedicated)) : null;
  if (who && model && a.dedicated && words.chips.dedicated_model) return fill(words.chips.dedicated_model, { who, model });
  if (who && model) return fill(words.chips.worker_model ?? "", { who, model });
  if (a.dedicated) return who ?? "";
  return a.who ?? words.chips.agent ?? "";
}

/** A finished step's chip names who did it; the record itself is a "Record" link in the list, never a hash. */
function doneChipText(words: RequestStatusNoun, raw: string | undefined, _receipt: string | undefined): string | null {
  return workerLabel(words, raw) ?? null;
}

function decisionLabel(words: RequestStatusNoun, choice: DecisionChoice): string {
  return (choice === "use" ? words.nodes.used : choice === "changes" ? words.nodes.changes : words.nodes.not_used) ?? "";
}

function sourcesText(words: RequestStatusNoun, n: number | undefined): string | undefined {
  if (!n) return undefined;
  return n === 1 ? words.chips.one_source : fill(words.chips.sources ?? "", { n });
}

/** One line per fact, newest first. Lines from public records without a write time keep their place. */
function logRows(record: StatusRecord, words: RequestStatusNoun): LogRow[] {
  const rows: LogRow[] = [];
  const parts = new Map<number, PartPlan>();
  const approvedParts = new Set<number>();
  const plannedBy = new Map<string, string>();
  for (const [index, event] of record.events.entries()) {
    if (event.type === "heartbeat" || !(event.receipt || event.ref)) continue;
    const n = event.part ?? 0;
    const w = workerLabel(words, event.worker, event.dedicated);
    const lease = event.lease_ends && event.at ? Math.round((event.lease_ends - event.at) / 60) : null;
    let text = "";
    switch (event.type) {
      case "received":
        text = words.log.received ?? "";
        break;
      case "plan_claimed":
        text = w ? fill(words.log.plan_claimed ?? "", { who: w }) : (words.log.plan_claimed_anon ?? "");
        if (w) plannedBy.set("plan", w);
        break;
      case "planned": {
        for (const p of event.parts ?? []) parts.set(p.part, p);
        const count = (event.parts ?? []).length;
        const by = w ?? plannedBy.get("plan");
        const key = count === 1 ? (by ? "planned_one" : "planned_one_anon") : by ? "planned" : "planned_anon";
        text = fill(words.log[key] ?? "", { n: count, who: by ?? "" });
        break;
      }
      case "blocked":
        text = fill(words.log.blocked ?? "", { reason: (event.findings ?? [event.reason ?? ""]).join("; ") });
        break;
      case "plan_released":
        text =
          event.reason && words.log.plan_released_reason
            ? fill(words.log.plan_released_reason, { who: w ?? words.chips.agent ?? "", reason: event.reason })
            : fill(words.log.plan_released ?? "", { who: w ?? words.chips.agent ?? "" });
        break;
      case "work_claimed":
        text =
          fill(words.log.work_claimed ?? "", { n, who: w ?? words.chips.agent ?? "" }) +
          (lease ? fill(words.log.lease ?? "", { m: lease }) : "");
        break;
      case "work_released":
        text =
          event.reason && words.log.released_reason
            ? fill(words.log.released_reason, { who: w ?? words.chips.agent ?? "", n, reason: event.reason })
            : fill(words.log.released ?? "", { who: w ?? words.chips.agent ?? "", n });
        break;
      case "work_submitted":
        text = event.summary?.sources
          ? fill(words.log.work_submitted_summary ?? "", {
              n,
              summary:
                event.summary.sources === 1
                  ? (words.chips.one_source ?? "")
                  : fill(words.chips.sources ?? "", { n: event.summary.sources }),
            })
          : fill(words.log.work_submitted ?? "", { n });
        break;
      case "check_claimed":
        text = fill(words.log.check_claimed ?? "", { n, who: w ?? words.chips.agent ?? "" });
        break;
      case "in_review":
        text = fill(words.log.in_review ?? "", { n });
        break;
      case "check_approved":
        if (n) approvedParts.add(n);
        text = w ? fill(words.log.approved ?? "", { n, who: w }) : fill(words.log.approved_anon ?? "", { n });
        break;
      case "check_sent_back":
        text = fill(words.log.sent_back ?? "", { n, reason: event.reason ?? "" });
        break;
      case "signoff_required":
        text = fill(words.log.signoff_required ?? "", { n });
        break;
      case "signed_off":
        text = fill(words.log.signed_off ?? "", { n });
        break;
      case "delivered":
        if (n) approvedParts.add(n);
        text = fill(words.log.delivered ?? "", { n });
        break;
      case "published":
        if (n) approvedParts.add(n);
        text = fill(words.log.published ?? "", { n });
        break;
      case "queued":
        text = event.part
          ? fill(words.log.queued ?? "", { nth: ordinal(event.places?.[String(event.part)] ?? event.place ?? 1), n })
          : fill(words.log.queued_plan ?? "", { nth: ordinal(event.place ?? 1) });
        break;
      case "library_added":
        text = fill(words.log.library_added ?? "", { n });
        break;
      case "decided":
        text = fill(
          words.log[event.choice === "use" ? "decided_use" : event.choice === "changes" ? "decided_changes" : "decided_dont"] ?? "",
          { n },
        );
        break;
      case "closed":
        text = parts.size > 0 && approvedParts.size === 0 ? (words.log.closed_unfinished ?? words.log.closed ?? "") : (words.log.closed ?? "");
        break;
      case "withdrawn":
        text = words.log.withdrawn ?? "";
        break;
    }
    rows.push({ key: `${index}-${event.type}-${n}`, at: event.at ?? null, text, evidence: event.receipt ?? event.ref });
  }
  return rows.reverse();
}

function stateWord(words: RequestStatusNoun, state: NodeState): string {
  return words.states[state] ?? state;
}

export function deriveView(record: StatusRecord, words: RequestStatusNoun, options: DeriveOptions): StatusView {
  const live = record.mode === "live";
  const facts = applyEvents(record.events, live);
  const shortId = shortRequestId(record.request.id);
  const estimate = pickupEstimate(record.estimate, options.now);
  const inLine = (place?: number) =>
    placeLine({ in_line: words.chips.in_line ?? "", estimate: words.chips.estimate ?? "" }, place, estimate);

  const planned = facts.plan === "done";
  const count = facts.parts.length;
  // Until the plan exists there are no parts to draw, so the diagram keeps one row's height.
  const center = planned && count > 0 ? FIRST_ROW + ((count - 1) * ROW) / 2 : FIRST_ROW;
  const height = planned && count > 0 ? Math.max(150, count * ROW) : ROW;

  const nodes: NodeView[] = [];
  const chips: ChipView[] = [];
  const edges: EdgeView[] = [];
  const labels: StatusView["labels"] = [];

  nodes.push({
    id: "request",
    kind: "request",
    state: "noun",
    label: words.nodes.request ?? "",
    sub: shortId,
    evidence: facts.received?.ref ?? facts.received?.receipt ?? record.request.id,
    ...COL.request,
    y: center - COL.request.h / 2,
  });

  const planState: NodeState = facts.plan === "stopped" ? "stopped" : facts.plan;
  const planLabel =
    facts.plan === "done"
      ? words.nodes.planned
      : facts.plan === "working"
        ? words.nodes.planning
        : facts.plan === "stopped"
          ? words.nodes.not_taken
          : words.nodes.plan;
  nodes.push({
    id: "plan",
    kind: "plan",
    state: planState,
    label: planLabel ?? "",
    sub: planned ? (count === 1 ? words.nodes.one_part : fill(words.nodes.parts ?? "", { n: count })) : undefined,
    evidence:
      facts.plan === "working"
        ? facts.planAgent?.receipt
        : facts.plan === "done"
          ? evidenceOf(facts.planEvidence)
          : facts.plan === "stopped"
            ? evidenceOf(facts.blocked)
            : facts.received?.ref,
    ...COL.plan,
    y: center - COL.plan.h / 2,
  });
  const planChipY = center + 34;
  if (facts.plan === "waiting") {
    const line = inLine(facts.planPlace);
    if (line) chips.push({ id: "plan-chip", node: "plan", x: COL.plan.x, y: planChipY, text: line, kind: "plain" });
  } else if (facts.plan === "working" && facts.planAgent) {
    chips.push({
      id: "plan-chip",
      node: "plan",
      x: COL.plan.x,
      y: planChipY,
      text: agentChipText(words, facts.planAgent, options),
      kind: "agent",
      lease:
        facts.planAgent.claimedAt && facts.planAgent.leaseEnds
          ? { start: facts.planAgent.claimedAt, end: facts.planAgent.leaseEnds }
          : undefined,
    });
  } else if (facts.plan === "done") {
    const text = doneChipText(words, facts.planEvidence?.who, facts.planEvidence?.receipt);
    if (text) chips.push({ id: "plan-chip", node: "plan", x: COL.plan.x, y: planChipY, text, kind: "plain" });
  }

  edges.push({ id: "e-request-plan", x1: 140, y1: center, x2: 174, y2: center, head: true, done: true, to: "plan" });
  if (!planned) labels.push({ id: "plan-hint", x: COL.queue.x, y: center - 12, text: words.diagram.plan_hint ?? "" });

  const parts: PartCardView[] = [];
  let yourTurnPart: number | undefined;

  for (const [index, p] of facts.parts.entries()) {
    const n = p.plan.part;
    const processPart = p.plan.route === "private-files" || p.plan.route === "process" || p.plan.output_type === "process";
    const held = p.plan.route === "held";
    const rc = rowCenter(index);
    const rowLabel = held ? words.diagram.row_held : processPart ? words.diagram.row_process : words.diagram.row_report;
    labels.push({ id: `row-${n}`, x: COL.queue.x, y: rc - 58, text: fill(rowLabel ?? "", { n }) });

    if (count === 1) {
      edges.push({ id: `e-plan-${n}`, x1: 285, y1: center, x2: 319, y2: rc, head: true, done: planned, to: `queue-${n}` });
    } else {
      if (index === 0) {
        edges.push({ id: "e-plan-fork", x1: 285, y1: center, x2: FORK_X, y2: center, head: false, done: planned });
        edges.push({ id: "e-fork", x1: FORK_X, y1: rowCenter(0), x2: FORK_X, y2: rowCenter(count - 1), head: false, done: planned });
      }
      edges.push({ id: `e-plan-${n}`, x1: FORK_X, y1: rc, x2: 319, y2: rc, head: true, done: planned, to: `queue-${n}` });
    }
    const pickedUp = p.work === "working" || p.work === "done";
    edges.push({ id: `e-queue-${n}`, x1: 450, y1: rc, x2: 529, y2: rc, head: true, done: pickedUp, to: `worker-${n}` });
    edges.push({ id: `e-worker-${n}`, x1: 720, y1: rc, x2: 759, y2: rc, head: true, done: p.work === "done", to: `review-${n}` });
    edges.push({ id: `e-review-${n}`, x1: 910, y1: rc, x2: 949, y2: rc, head: true, done: p.check === "approved", to: `result-${n}` });

    const stopped = Boolean(facts.withdrawn);
    // The queue: waiting in line until a worker picks the part up.
    const queueState: NodeState = held ? "held" : pickedUp ? "done" : stopped ? "idle" : p.work === "open" ? "open" : "waiting";
    nodes.push({
      id: `queue-${n}`,
      kind: "queue",
      part: n,
      state: queueState,
      label: (held ? words.nodes.held : pickedUp ? words.nodes.picked_up : words.nodes.queue) ?? "",
      evidence: pickedUp
        ? (p.workAgent?.receipt ?? evidenceOf(p.submitted) ?? evidenceOf(p.checkEvidence) ?? evidenceOf(p.resultEvidence))
        : queueState === "idle"
          ? undefined
          : evidenceOf(facts.planEvidence),
      ...COL.queue,
      y: rc - COL.queue.h / 2,
    });
    const chipY = rc + 34;
    if (!pickedUp && !held && !stopped) {
      const line = inLine(p.place);
      if (line) chips.push({ id: `queue-chip-${n}`, node: `queue-${n}`, x: COL.queue.x, y: chipY, text: line, kind: "plain" });
    }

    // The worker: "A worker is now working on this" from the claim until the draft is in.
    const workerState: NodeState = p.work === "working" ? "working" : p.work === "done" ? "done" : "idle";
    nodes.push({
      id: `worker-${n}`,
      kind: "worker",
      part: n,
      state: workerState,
      label: (p.work === "working" ? words.nodes.working : p.work === "done" ? words.nodes.draft_ready : words.nodes.worker) ?? "",
      evidence:
        p.work === "working"
          ? p.workAgent?.receipt
          : p.work === "done"
            ? (evidenceOf(p.submitted) ?? evidenceOf(p.checkEvidence) ?? evidenceOf(p.resultEvidence))
            : undefined,
      ...COL.worker,
      y: rc - COL.worker.h / 2,
    });
    if (p.work === "working" && p.workAgent) {
      chips.push({
        id: `worker-chip-${n}`,
        node: `worker-${n}`,
        x: COL.worker.x,
        y: rc + 40,
        text: agentChipText(words, p.workAgent, options),
        kind: "agent",
        lease: p.workAgent.claimedAt && p.workAgent.leaseEnds ? { start: p.workAgent.claimedAt, end: p.workAgent.leaseEnds } : undefined,
      });
    } else if (p.work === "done" && p.submitted) {
      const text = doneChipText(words, p.submitted.who, p.submitted.receipt);
      if (text) chips.push({ id: `worker-chip-${n}`, node: `worker-${n}`, x: COL.worker.x, y: rc + 40, text, kind: "plain" });
    }

    // The independent review, by a different worker.
    const reviewState: NodeState = held || (stopped && p.check !== "approved") ? "idle" : p.check === "open" ? "idle" : p.check;
    nodes.push({
      id: `review-${n}`,
      kind: "review",
      part: n,
      state: reviewState,
      label:
        (p.check === "working"
          ? words.nodes.checking
          : p.check === "approved"
            ? words.nodes.approved
            : p.check === "sent_back"
              ? words.nodes.sent_back
              : words.nodes.review) ?? "",
      evidence:
        reviewState === "working"
          ? (p.checkAgent?.receipt ?? evidenceOf(p.checkEvidence))
          : reviewState === "approved" || reviewState === "sent_back"
            ? evidenceOf(p.checkEvidence)
            : undefined,
      ...COL.review,
      y: rc - COL.review.h / 2,
    });
    if (p.check === "working" && p.checkAgent) {
      chips.push({
        id: `review-chip-${n}`,
        node: `review-${n}`,
        x: COL.review.x,
        y: chipY,
        text: agentChipText(words, p.checkAgent, options),
        kind: "agent",
        lease: p.checkAgent.claimedAt && p.checkAgent.leaseEnds ? { start: p.checkAgent.claimedAt, end: p.checkAgent.leaseEnds } : undefined,
      });
    } else if (p.check === "approved") {
      const text = doneChipText(words, p.checkEvidence?.who, p.checkEvidence?.receipt);
      if (text) chips.push({ id: `review-chip-${n}`, node: `review-${n}`, x: COL.review.x, y: chipY, text, kind: "plain" });
    }

    // The result: a cited report or a reusable process, then your decision.
    const resultHref = held ? undefined : options.resultHref(n);
    const resultState: NodeState = p.decide === "idle" ? "idle" : p.decide === "person" ? "person" : p.decide;
    const kindLabel = (processPart ? words.nodes.process : words.nodes.report) ?? "";
    const resultSub =
      p.decide === "decided" && p.decision
        ? decisionLabel(words, p.decision.choice)
        : p.decide === "yourturn"
          ? words.nodes.your_turn
          : p.decide === "person"
            ? words.nodes.signoff
            : processPart
              ? undefined
              : sourcesText(words, p.submitted?.sources);
    nodes.push({
      id: `result-${n}`,
      kind: "result",
      part: n,
      state: resultState,
      label: kindLabel,
      sub: resultSub,
      evidence: p.decide === "decided" ? evidenceOf(p.decision) : p.decide === "idle" ? undefined : evidenceOf(p.decideEvidence),
      ...COL.result,
      y: rc - COL.result.h / 2,
    });
    if (p.decide === "yourturn") {
      if (yourTurnPart === undefined) yourTurnPart = n;
      if (resultHref) {
        chips.push({
          id: `result-chip-${n}`,
          node: `result-${n}`,
          x: COL.result.x,
          y: rc + 40,
          text: `${processPart ? words.chips.see_process : words.chips.read_report} →`,
          kind: "link",
          href: resultHref,
        });
      }
    } else if (p.decide === "decided" && p.decision) {
      chips.push({
        id: `result-chip-${n}`,
        node: `result-${n}`,
        x: COL.result.x,
        y: rc + 40,
        text: p.decision.at ? fill(words.chips.by_team ?? "", { time: options.formatClock(p.decision.at) }) : decisionLabel(words, p.decision.choice),
        kind: "plain",
      });
    }

    // The same part as a card, for the list view and phones.
    const node = (id: string) => nodes.find((each) => each.id === id);
    const q = node(`queue-${n}`);
    const wk = node(`worker-${n}`);
    const rv = node(`review-${n}`);
    const rs = node(`result-${n}`);
    const steps: StepView[] = [
      {
        key: `queue-${n}`,
        label: words.list.queue ?? "",
        state: q?.state ?? "idle",
        word: (pickedUp ? words.nodes.picked_up : held ? words.nodes.held : stateWord(words, q?.state ?? "idle")) ?? "",
        detail: pickedUp || held ? undefined : (inLine(p.place) ?? undefined),
        evidence: q?.evidence,
      },
      {
        key: `worker-${n}`,
        label: words.list.worker ?? "",
        state: wk?.state ?? "idle",
        word: (p.work === "working" ? words.nodes.working : p.work === "done" ? words.nodes.draft_ready : stateWord(words, "idle")) ?? "",
        detail:
          p.work === "working" && p.workAgent
            ? [agentChipText(words, p.workAgent, options), p.workAgent.leaseEnds ? fill(words.chips.lease ?? "", { time: options.formatClock(p.workAgent.leaseEnds) }) : null]
                .filter(Boolean)
                .join(" · ")
            : p.work === "done"
              ? [p.submitted?.who, processPart ? null : sourcesText(words, p.submitted?.sources)].filter(Boolean).join(" · ") || undefined
              : p.released?.reason,
        evidence: wk?.evidence,
      },
      {
        key: `review-${n}`,
        label: words.list.review ?? "",
        state: rv?.state ?? "idle",
        word: rv?.label && rv.state !== "idle" ? rv.label : stateWord(words, "idle"),
        detail:
          p.check === "working" && p.checkAgent
            ? agentChipText(words, p.checkAgent, options)
            : p.check === "approved"
              ? p.checkEvidence?.who
              : p.check === "sent_back"
                ? p.checkEvidence?.reason
                : undefined,
        evidence: rv?.evidence,
      },
      {
        key: `result-${n}`,
        label: words.list.result ?? "",
        state: rs?.state ?? "idle",
        word: (rs && rs.state !== "idle" ? rs.sub : stateWord(words, "idle")) ?? "",
        detail: p.decide === "decided" && p.decision?.at ? fill(words.chips.by_team ?? "", { time: options.formatClock(p.decision.at) }) : undefined,
        evidence: rs?.evidence,
        href: p.decide === "yourturn" || p.decide === "decided" ? resultHref : undefined,
        action: p.decide === "yourturn" || p.decide === "decided" ? (processPart ? words.list.see_process : words.list.read_report) : undefined,
      },
    ];
    parts.push({
      part: n,
      route: p.plan.route,
      title: fill((held ? words.list.held_title : processPart ? words.list.process_title : words.list.report_title) ?? "", { n }),
      subtitle: (held ? words.list.held_sub : processPart ? words.list.process_sub : words.list.report_sub) ?? "",
      steps: held ? steps.slice(0, 1) : steps,
      note: processPart ? (p.plan.needs_person_signoff ? words.list.signoff_note : words.list.process_note) : undefined,
    });
  }

  const planCard: StepView = {
    key: "plan",
    label: words.list.plan_title ?? "",
    state: planState,
    word: (planLabel ?? "") + (planned ? ` · ${count === 1 ? words.nodes.one_part : fill(words.nodes.parts ?? "", { n: count })}` : ""),
    detail:
      facts.plan === "working" && facts.planAgent
        ? agentChipText(words, facts.planAgent, options)
        : facts.plan === "waiting"
          ? (inLine(facts.planPlace) ?? undefined)
          : facts.plan === "done"
            ? (doneChipText(words, facts.planEvidence?.who, facts.planEvidence?.receipt) ?? undefined)
            : undefined,
    evidence: nodes.find((each) => each.id === "plan")?.evidence,
  };

  // The overall chip, the line a screen reader hears and the tab title.
  const anyDecided = facts.parts.find((p) => p.decide === "decided");
  const anyApproved = facts.parts.some((p) => p.check === "approved" || p.decide === "yourturn" || p.decide === "decided");
  const allWaiting = facts.parts.every((p) => ["waiting", "open", "held"].includes(p.work) && p.check !== "working");
  let overall: StatusView["overall"];
  if (facts.withdrawn) overall = { label: words.overall.withdrawn ?? "", tone: "waiting" };
  else if (facts.plan === "stopped") overall = { label: words.overall.blocked ?? "", tone: "caution" };
  else if (facts.closed && facts.parts.length > 0 && !anyApproved)
    overall = { label: words.overall.unfinished ?? words.overall.finished ?? "", tone: "caution" };
  else if (facts.closed) overall = { label: words.overall.finished ?? "", tone: "real" };
  else if (yourTurnPart !== undefined) overall = { label: fill(words.overall.your_turn ?? "", { n: yourTurnPart }), tone: "attention" };
  else if (anyDecided && anyDecided.decision?.choice === "use")
    overall = { label: fill(words.overall.used_progress ?? "", { n: anyDecided.plan.part }), tone: "real" };
  else if (anyDecided) overall = { label: words.overall.decided ?? "", tone: "real" };
  else if (planned && allWaiting) overall = { label: words.overall.planned ?? "", tone: "waiting" };
  else if (facts.plan === "working") overall = { label: words.overall.planning ?? "", tone: "verb" };
  else if (facts.plan === "waiting") overall = { label: words.overall.waiting ?? "", tone: "waiting" };
  else overall = { label: words.overall.progress ?? "", tone: "verb" };

  const docTitle =
    record.mode === "example"
      ? (words.titles.doc_example ?? "")
      : yourTurnPart !== undefined
        ? fill(words.titles.doc_turn ?? "", { short: shortId })
        : fill(words.titles.doc ?? "", { short: shortId });

  const recordOf = new Map<string, string>();
  for (const event of record.events) {
    if (event.record && (event.receipt || event.ref)) recordOf.set((event.receipt ?? event.ref) as string, event.record);
  }
  for (const node of nodes) if (node.evidence && recordOf.has(node.evidence)) node.record = recordOf.get(node.evidence);

  return {
    id: record.request.id,
    shortId,
    title: record.request.title ?? "",
    overall,
    nodes,
    edges,
    chips,
    labels,
    height,
    planned,
    log: logRows(record, words),
    parts,
    planCard,
    summary: summaryLine(record.events, words),
    docTitle,
    yourTurnPart,
    queue: facts.queue,
    estimate,
    facts,
  };
}

/** The sentence a screen reader hears after a change: the last fact, plus "Your turn." when it is. */
export function summaryLine(events: StatusEvent[], words: RequestStatusNoun): string {
  const last = [...events].reverse().find((event) => event.type !== "heartbeat" && (event.receipt || event.ref));
  if (!last) return words.summary.waiting ?? "";
  const n = last.part ?? 0;
  switch (last.type) {
    case "received":
    case "plan_released":
      return words.summary.waiting ?? "";
    case "plan_claimed":
      return words.summary.planning ?? "";
    case "planned":
      return fill(words.summary.planned ?? "", { n: (last.parts ?? []).length });
    case "blocked":
      return words.summary.blocked ?? "";
    case "work_claimed":
      return fill(words.summary.part_working ?? "", { n });
    case "work_released":
      return last.reason
        ? `${fill(words.summary.part_released ?? "", { n })} (${last.reason})`
        : fill(words.summary.part_released ?? "", { n });
    case "work_submitted":
      return fill(words.summary.part_ready ?? "", { n });
    case "check_claimed":
    case "in_review":
      return fill(words.summary.part_checking ?? "", { n });
    case "check_approved":
      return fill(words.summary.part_approved ?? "", { n });
    case "check_sent_back":
      return fill(words.summary.part_sent_back ?? "", { n });
    case "signoff_required":
    case "signed_off":
      return fill(words.summary.signoff ?? "", { n });
    case "delivered":
    case "published":
      return `${fill(words.summary.part_approved ?? "", { n })} ${words.summary.your_turn ?? ""}`.trim();
    case "decided":
      return fill(words.summary.decided ?? "", { n });
    case "closed": {
      const hadParts = events.some((e) => e.type === "planned" && (e.parts ?? []).length > 0);
      const hadApproved = events.some((e) => e.type === "check_approved" || e.type === "delivered" || e.type === "published");
      return hadParts && !hadApproved ? (words.summary.closed_unfinished ?? words.summary.closed ?? "") : (words.summary.closed ?? "");
    }
    case "withdrawn":
      return words.log.withdrawn ?? "";
    default:
      return "";
  }
}

/** Events up to a named moment of an example run, for fixtures and screenshots. */
export function eventsAtMoment(events: StatusEvent[], moments: Record<string, number>, moment: string): StatusEvent[] {
  const count = moments[moment];
  return count === undefined ? events : events.slice(0, count);
}
