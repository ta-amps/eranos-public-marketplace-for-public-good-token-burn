import type { Frequency, OutputType } from "./types";

/**
 * What the request box just sent, kept in this tab's memory for the moment between Send and Tessera's first
 * answer, so the status page can show the request at once. It is never stored or sent anywhere.
 */
export interface SentRequest {
  text: string;
  organization_type: string;
  output_type: string;
  frequency: string;
  sent_at: number;
}

const sent = new Map<string, SentRequest>();

export function rememberSent(id: string, request: SentRequest): void {
  sent.set(id, request);
}

export function sentRequest(id: string): (SentRequest & { output_type: OutputType | string; frequency: Frequency | string }) | null {
  return sent.get(id) ?? null;
}
