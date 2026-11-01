import { fill } from "../nouns";
import type { EstimateInput } from "./types";

const DAY = 86_400;

export interface PickupEstimate {
  /** Rounded down, in minutes: the 25th percentile of the last 50 pick-up delays. */
  low: number;
  /** Rounded up, in minutes: the 75th percentile. Always more than `low`. */
  high: number;
}

/** The q-th quantile of sorted values, interpolating between the two closest ranks. */
export function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) throw new Error("no values");
  const index = (sorted.length - 1) * q;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  const a = sorted[lower] ?? 0;
  const b = sorted[upper] ?? a;
  return a + (b - a) * (index - lower);
}

/**
 * "Usually picked up in A–B min": the middle half (25th to 75th percentile) of the last 50 pick-up delays. It is
 * hidden (null) when fewer than 10 claims happened in the last 7 days, or none in the last 24 hours, because then
 * the numbers say nothing about today.
 */
export function pickupEstimate(input: EstimateInput | null | undefined, now: number): PickupEstimate | null {
  if (!input) return null;
  const recent = input.claim_times.filter((t) => t <= now && t >= now - 7 * DAY);
  if (recent.length < 10) return null;
  const last = Math.max(...input.claim_times.filter((t) => t <= now));
  if (!Number.isFinite(last) || last < now - DAY) return null;
  const delays = input.claim_delays_s.filter((d) => Number.isFinite(d) && d >= 0).slice(-50);
  if (delays.length < 10) return null;
  const sorted = [...delays].sort((a, b) => a - b);
  const low = Math.max(1, Math.floor(quantile(sorted, 0.25) / 60));
  const high = Math.max(low + 1, Math.ceil(quantile(sorted, 0.75) / 60));
  return { low, high };
}

/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/** "2nd in line · usually 5–20 min", "2nd in line" without an estimate, or null without a place. */
export function placeLine(
  words: { in_line: string; estimate: string },
  place: number | null | undefined,
  estimate: PickupEstimate | null,
): string | null {
  if (!place || place < 1) return null;
  const line = fill(words.in_line, { nth: ordinal(place) });
  return estimate ? `${line} · ${fill(words.estimate, { a: estimate.low, b: estimate.high })}` : line;
}
