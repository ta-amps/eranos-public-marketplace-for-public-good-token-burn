import type { EstimateInput, RequestInfo, StatusEvent, StatusRecord } from "./types";

/**
 * The example request (`eranos.instructions/request-example`): a list of facts with the times they
 * would have, replayed at reading speed. Nothing in it was sent. Its ids and claim receipts use the real
 * formulas on example inputs; its submit and review receipts are stand-in hashes of example payloads.
 */
export interface RequestExampleNoun {
  is_example: true;
  mark: string;
  about: string;
  request: RequestInfo & { title: string; text: string; sent_at: number };
  queue_estimate: EstimateInput;
  moments: Record<string, number>;
  events: StatusEvent[];
  solution: ExampleSolution;
}

export interface ReportSource {
  id: string;
  title: string;
  url: string;
  access?: string;
  public?: boolean;
  is_example?: boolean;
  published?: string;
  publisher?: string;
}

export interface ReportClaim {
  id: string;
  text?: string;
  citations: { source: string; quote: string }[];
  unclear?: boolean;
}

export interface Report {
  report_id: string;
  request_id: string;
  title: string;
  question?: string;
  summary?: string | string[];
  claims: ReportClaim[];
  sources: ReportSource[];
  decision?: string;
  disclaimer?: string;
}

/** A delivered report, as `eranos.solutions/<report_id>` holds it. */
export interface ExampleSolution {
  request_id: string;
  report: Report;
  report_sha256?: string;
  review_task_id?: string;
  review_receipt?: string;
  research_receipt?: string | null;
  next_step?: string;
  is_example?: boolean;
}

export const EXAMPLE_ID = "example";
export const MOMENTS = ["received", "planned", "working", "review", "your-turn", "decided"] as const;
export type Moment = (typeof MOMENTS)[number];

export function exampleRecord(noun: RequestExampleNoun, count: number): StatusRecord {
  return {
    mode: "example",
    request: noun.request,
    events: noun.events.slice(0, Math.max(1, Math.min(count, noun.events.length))),
    estimate: noun.queue_estimate,
  };
}

/** The example's own clock at a point in the replay: the time of the last fact shown. */
export function exampleNow(noun: RequestExampleNoun, count: number): number {
  const shown = noun.events.slice(0, Math.max(1, count));
  return shown[shown.length - 1]?.at ?? noun.request.sent_at;
}
