/**
 * A request's status is a list of facts, in the order they happened. Each fact carries the receipt hash Tessera
 * wrote for it, or, where Tessera writes no hash, a reference to the public record that holds it. The page draws
 * every node, chip and log line from these facts and nothing else, so no step can show as done without one.
 */

export type PartRoute = "public-only" | "private-files" | "held";

/** One part of a plan, as the classify step records it in `eranos.plans/<request_id>`. */
export interface PartPlan {
  part: number;
  route: PartRoute;
  text: string;
  legal?: boolean;
  output_type?: string;
  frequency?: string;
  report_id?: string;
  kit_id?: string;
  track_id?: string;
  needs_person_signoff?: boolean;
  work_task_id?: string;
  review_task_id?: string;
}

/** Counts of Eranos's queues at one moment, and the agents holding work when that is known. */
export interface QueueSnapshot {
  waiting: number;
  working: number;
  checking: number;
  agents: string[];
}

export type StatusEventType =
  | "received"
  | "plan_claimed"
  | "plan_released"
  | "planned"
  | "blocked"
  | "queued"
  | "work_claimed"
  | "work_released"
  | "work_submitted"
  | "check_claimed"
  | "in_review"
  | "check_approved"
  | "check_sent_back"
  | "signoff_required"
  | "signed_off"
  | "delivered"
  | "published"
  | "library_added"
  | "check_refused"
  | "decided"
  | "heartbeat"
  | "closed"
  | "withdrawn";

export type DecisionChoice = "use" | "changes" | "dont";

export interface StatusEvent {
  type: StatusEventType;
  /** Unix seconds. Null when the public record that holds the fact does not carry its write time. */
  at?: number | null;
  part?: number;
  /** A receipt hash Tessera wrote. */
  receipt?: string;
  /** A record reference, where Tessera writes no hash for the fact. */
  ref?: string;
  worker?: string;
  model?: string;
  lease_ends?: number;
  /** True when one of Eranos's own (dedicated) workers claimed it because no volunteer was free in time. */
  dedicated?: boolean;
  parts?: PartPlan[];
  /** Places in line, by part number, after this fact. */
  places?: Record<string, number>;
  /** The plan's place in line, before it is claimed. */
  place?: number;
  queue?: QueueSnapshot;
  summary?: { sources?: number };
  reason?: string;
  findings?: string[];
  choice?: DecisionChoice;
  result_id?: string;
  note?: string;
  library_ref?: string;
  /** The public address that holds this fact, such as a version of /api/nouns/eranos.requests/<id>/history. */
  record?: string;
  /** Example runs only: when this fact appears in the replay, in milliseconds from the start. */
  replay_ms?: number;
  version?: number;
}

export type OutputType = "process" | "information";
export type Frequency = "one-off" | "recurring";

export interface RequestInfo {
  id: string;
  title?: string;
  /** The request text, the nonprofit's own description; null when it was removed from the public record. */
  text?: string | null;
  organization_type?: string;
  /** What the nonprofit asked for: a reusable process its own agent runs, or information from public sources. */
  output_type?: OutputType;
  frequency?: Frequency;
  cadence?: string;
  sent_at?: number | null;
}

/** The pick-up estimate's inputs: the queue's recent claim delays and claim times, in seconds. */
export interface EstimateInput {
  claim_delays_s: number[];
  claim_times: number[];
  as_of: number;
}

export interface StatusRecord {
  mode: "example" | "live";
  request: RequestInfo;
  events: StatusEvent[];
  estimate?: EstimateInput | null;
}

/** A fact's identity, so a poll that returns the same facts again animates nothing. */
export function eventKey(event: StatusEvent): string {
  return [event.type, event.part ?? "", event.receipt ?? event.ref ?? "", event.at ?? ""].join("|");
}
