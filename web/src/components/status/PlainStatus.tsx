import { useEffect, useRef, useState } from "react";

import { AGORA_HOW_IT_WORKS_URL } from "../../lib/marketplace";
import { fill, type PlainWords } from "../../lib/nouns";
import { applyEvents, noResultCause, outsideVolunteer, ownWorker, plainEvent, withoutOwnLabel, type Facts } from "../../lib/status/derive";
import { ordinal } from "../../lib/status/estimate";
import type { StatusEvent } from "../../lib/status/types";
import { AppLink, useHash } from "../../router";

/**
 * The request page's plain view (RequestStatusPage v6, Claude Design 20:15): a progress strip and four bands, in
 * plain words. No volunteer names, ids or receipts; those stay in the technical view. Every line is read from the
 * same recorded facts as the diagram, so the two views never disagree.
 */

/**
 * A step's state; "closed" is a step the request closed before reaching, and "skipped" one it never needed (a library
 * answer made nothing new).
 */
type StageState = "done" | "now" | "upcoming" | "closed" | "skipped";
type Kind = "process" | "information";
type Part = Facts["parts"][number];

/** A task nobody claims within this time goes to one of Eranos's own workers ("volunteers first"). */
const FALLBACK_SECONDS = 90;

function kindOf(part: Part): Kind {
  const declared = part.plan.output_type;
  if (declared === "process" || declared === "information") return declared;
  if (part.plan.route === "reused") {
    const from = (part.plan as { reused_from?: { kind?: string } }).reused_from;
    return from?.kind === "report" ? "information" : "process";
  }
  return part.plan.route === "private-files" || part.plan.route === "process" ? "process" : "information";
}

function cleanPlainReason(raw: string | undefined): string {
  if (!raw) return "";
  return raw
    .replace(/^ReviewRefused:\s*/i, "")
    .replace(/\b[0-9a-f]{12,}\b/gi, "")
    .replace(/\bR-[A-Z0-9]{4}\b/g, "")
    .replace(/\b(?:wren|kestrel|heron)-[a-z0-9-]+\b/gi, "a worker")
    .replace(/\s+/g, " ")
    .trim();
}

/** A date and time for a run that may be days away. */
function when(at: number): string {
  return new Date(at * 1000).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** The first sentence of a worker's reason, short enough for one line. */
function shortReason(reason: string): string {
  const first = reason.split(/(?<=[.!?])\s/)[0] ?? reason;
  if (first.length > 140) return `${first.slice(0, 138)}\u2026`;
  return /[.!?\u2026]$/.test(first) ? first : `${first}.`;
}

/** True when one of Eranos's own (dedicated) workers recorded the fact. */
const byEranos = ownWorker;

/** Where a reused answer came from: its catalog page, or the public record that holds it. */
function sourceHref(event: StatusEvent): string | null {
  if (/^(KIT|PRC)-/.test(event.result_id ?? "")) return `/catalog/${encodeURIComponent(event.result_id ?? "")}`;
  const ref = /^(eranos\.[a-z_.]+)\/([A-Za-z0-9][A-Za-z0-9_.:-]*)/.exec(event.ref ?? "");
  return ref ? `/api/nouns/${ref[1]}/${encodeURIComponent(ref[2] ?? "")}` : null;
}

/** A part is being remade after the requester asked for changes, until a new check approves it. */
function changing(part: Part): boolean {
  return part.decision?.choice === "changes" && part.decide !== "yourturn";
}

export interface PlainSummary {
  /** The four bands' states (sorted, made, checked, ready), in order. */
  bands: StageState[];
  /** The request track (owner v2, Nov 1): one station and its tone, the one source for the token and aria-current. */
  track: TrackState;
  chip: string;
  waiting: boolean;
  yourTurn: boolean;
}

/** wait: in line, or a person's turn to wait for; work: someone is on it; turn: a person decides; done: delivered. */
/** closed: the request closed with no result, so its last station is where it stopped, not where it waits. */
export type TrackTone = "wait" | "work" | "turn" | "done" | "closed";
export interface TrackState {
  at: number;
  tone: TrackTone;
  /** True when the request is back at "Being made": a check sent it back, or the team asked for changes. */
  back: boolean;
  /** Stations the request passed without doing them (a library answer: nothing made, maybe nothing checked). */
  skipped?: number[];
  /** True when the passed stations were not done (no check of the fit), not merely not needed. */
  skippedNotDone?: boolean;
}

/** Where one part stands on the six stations (CLAUDE-CODE-PROMPT §4.2 and the RequestStatusPage board's rule). */
function partStation(part: Part): TrackState {
  if (part.library || (part.decide === "decided" && part.decision?.choice !== "changes")) return { at: 5, tone: "done", back: false };
  if (changing(part) || part.check === "sent_back") return { at: 2, tone: "work", back: true };
  if (part.decide === "yourturn" || part.check === "approved") return { at: 5, tone: "turn", back: false };
  if (part.check === "working") return { at: 4, tone: "work", back: false };
  if (part.work === "done") return { at: 3, tone: "wait", back: false };
  if (part.work === "working") return { at: 1, tone: "work", back: false };
  return { at: 0, tone: "wait", back: false };
}

/**
 * The request's station: its least advanced part, so a second part's progress, a later decision or a recurring
 * run's next queue never moves it the wrong way. Before the plan exists, it is in line.
 */
export function trackState(facts: Facts): TrackState {
  const parts = facts.parts;
  if (facts.plan !== "done" || parts.length === 0) return { at: 0, tone: "wait", back: false };
  return parts.map(partStation).reduce((low, next) => (next.at < low.at ? next : low));
}

export function plainSummary(facts: Facts, words: PlainWords, every: string, requester = true): PlainSummary {
  const c = words.chip;
  // Answered from the library (F-UI-STALE-001): the request's own state decides the steps, and the top says how.
  // Nothing new was made, and it shows as checked only once a different key checked the fit for this request
  // (reuse_checked, F-REUSE-001); until then the Made and Checked stations are passed, not done.
  if (!facts.reused && facts.reuseCandidate && facts.reuseCheck?.verdict !== "does_not_fit" && !facts.closed) {
    // A similar library answer is being checked for this request: nothing is made; a different helper checks the fit.
    const fits = facts.reuseCheck?.verdict === "fits";
    return {
      bands: ["done", "skipped", fits ? "done" : "now", fits ? "now" : "upcoming"],
      track: { at: fits ? 5 : 4, tone: "work", back: false, skipped: fits ? [2] : [2, 3], skippedNotDone: !fits },
      chip: fits ? (c.reused ?? c.in_use) : (c.reuse_checking ?? c.checking),
      waiting: false,
      yourTurn: false,
    };
  }
  if (facts.reused) {
    const verdict = facts.reuseCheck?.verdict;
    const fits = verdict === "fits";
    const check: StageState = fits ? "done" : verdict === "does_not_fit" || facts.closed ? "closed" : "now";
    return {
      bands: ["done", "skipped", check, fits || facts.closed ? "done" : "upcoming"],
      track: { at: 5, tone: "done", back: false, skipped: fits ? [2] : [2, 3, 4], skippedNotDone: !fits },
      chip: fits ? (c.reused ?? c.in_use) : verdict === "does_not_fit" ? (c.reuse_does_not_fit ?? c.reused ?? c.in_use) : (c.reused_unchecked ?? c.reused ?? c.in_use),
      waiting: false,
      yourTurn: false,
    };
  }
  const parts = facts.parts;
  const planned = facts.plan === "done" && parts.length > 0;
  const anyWorking = parts.some((p) => p.work === "working");
  const allMade = planned && parts.every((p) => p.work === "done");
  const anyChecking = parts.some((p) => p.check === "working");
  const allChecked = planned && parts.every((p) => p.check === "approved");
  const anyApproved = parts.some((p) => p.check === "approved" || p.decide === "yourturn" || p.decide === "decided");
  // Closed with no result, with or without a plan: the steps it never reached are closed, not waiting to start.
  const closedUnfinished = Boolean(facts.closed) && !anyApproved && !facts.withdrawn && !facts.blocked;
  const sentBack = parts.some((p) => p.check === "sent_back");
  const waitingCheck = parts.some((p) => p.work === "done" && p.check !== "approved" && p.check !== "working" && p.check !== "sent_back");
  const yourTurn = parts.some((p) => p.decide === "yourturn");
  const allDecided = planned && parts.every((p) => p.decide === "decided");
  const used = parts.some((p) => p.decision?.choice === "use");
  const inLibrary = parts.some((p) => p.library);
  const remaking = parts.some(changing);
  const state = (done: boolean, now: boolean): StageState => (done ? "done" : now ? "now" : "upcoming");
  const open: StageState[] = [
    state(planned, !planned),
    state(allMade && !remaking, planned),
    state(allChecked && !remaking, anyChecking || waitingCheck || sentBack),
    state(allDecided, yourTurn || parts.some((p) => p.decide === "person")),
  ];
  const bands: StageState[] = closedUnfinished ? open.map((band) => (band === "done" ? "done" : "closed")) : open;

  const chip = facts.withdrawn
    ? c.withdrawn
    : facts.blocked
      ? c.blocked
      : closedUnfinished
        ? (c.unfinished ?? c.waiting_volunteer)
      : yourTurn
        ? requester
          ? c.ready
          : c.ready_public
        : allDecided
          ? used
            ? inLibrary
              ? c.in_use
              : every
                ? fill(c.in_use_regular, { every })
                : c.in_use_plain
            : c.not_used
          : remaking
            ? c.changes
            : sentBack
              ? c.sent_back
              : anyChecking
                ? c.checking
                : waitingCheck
                  ? c.waiting_check
                  : anyWorking
                    ? c.making
                    : planned
                      ? c.waiting_volunteer
                      : c.planning;
  const waiting = !facts.withdrawn && !facts.blocked && !closedUnfinished && !yourTurn && !allDecided && !anyWorking && !anyChecking;
  const track = trackState(facts);
  return { bands, track: closedUnfinished ? { ...track, tone: "closed" } : track, chip, waiting, yourTurn };
}

/** The board's caption names for the film frame (RequestStatusPage onEvent), from the recorded event types. */
/** The four bands' anchors (DESIGN-SPEC 0.2); the judge tour links to #step-ready. */
const BAND_IDS = ["step-split", "step-build", "step-review", "step-ready"];
/** Which band each of the six stations opens: In line, Picked up, Being made, In line for a check, Being checked, Ready. */
const STATION_BAND = [0, 1, 1, 2, 2, 3];

/** The station before the request's last move, so a page that opens on a settled request shows only that one hop. */
function stationBefore(events: StatusEvent[], now: TrackState): number {
  for (let n = events.length - 1; n > 0; n -= 1) {
    const earlier = trackState(applyEvents(events.slice(0, n))).at;
    if (earlier !== now.at) return earlier;
  }
  return now.at;
}

/**
 * The token. It mounts only on settled facts, at the station before the request's last move, and two frames later
 * moves to where the request is: one hop on load, then one move per change. With reduced motion it jumps.
 */
function TrackToken({ track, events }: { track: TrackState; events: StatusEvent[] }) {
  const [shown, setShown] = useState(() => stationBefore(events, track));
  const [animate, setAnimate] = useState(false);
  useEffect(() => {
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => {
        setAnimate(true);
        setShown(track.at);
      });
    });
    return () => {
      window.cancelAnimationFrame(outer);
      window.cancelAnimationFrame(inner);
    };
  }, [track.at]);
  return (
    <span className="er-track-lane" aria-hidden="true" data-animate={animate}>
      <span className="er-track-token" data-testid="track-token" data-pos={shown} data-tone={track.tone} data-back={track.back} />
    </span>
  );
}

/**
 * The request track (owner v2, Nov 1): six stations and one token, both from the request's state (trackState), so
 * the token and aria-current never disagree. The token moves 900 ms by transform only when the state changes; a
 * page that opens on a settled request shows only the last hop, and with reduced motion it jumps. A check that
 * sends the work back moves it backwards. Ghost pills stand for the requests ahead in line.
 */
function RequestTrack({
  track,
  events,
  words,
  label,
  ahead,
  settled,
  requester,
  onStation,
}: {
  track: TrackState;
  events: StatusEvent[];
  words: PlainWords["track"];
  label: string;
  ahead: number;
  settled: boolean;
  requester: boolean;
  /** Opens the band a station stands for (1 to 4). */
  onStation?: (band: number) => void;
}) {
  const delivered = track.tone === "done";
  // The track's measured height, as --er-track-h on the page: focus and anchors scroll clear of it at every width
  // (it is taller on phones, where the station names wrap). WCAG 2.2 SC 2.4.11.
  const nav = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = nav.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() => root.style.setProperty("--er-track-h", `${Math.ceil(element.getBoundingClientRect().height)}px`));
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--er-track-h");
    };
  }, []);
  return (
    <nav ref={nav} className="er-track" aria-label={label} data-testid="request-track">
      <ol>
        {words.stations.map((station, i) => {
          const passed = track.skipped?.includes(i) ?? false;
          const done = (i < track.at || (i === 5 && delivered)) && !passed;
          const stopped = i === track.at && track.tone === "closed";
          const now = i === track.at && !done && !stopped && !passed;
          const name = now ? (i === 5 && !requester ? (station.now_public ?? station.now) : station.now) : station.other;
          return (
            <li key={i} data-step={i} data-state={done ? "done" : now ? "now" : stopped ? "closed" : passed ? "skipped" : "upcoming"} data-tone={now ? track.tone : undefined}>
              <a href={`#${BAND_IDS[STATION_BAND[i] ?? 0]}`} aria-current={now ? "step" : undefined} onClick={() => onStation?.((STATION_BAND[i] ?? 0) + 1)}>
                <span className="er-track-dot" aria-hidden="true" />
                <span className="er-track-name">{name}</span>
                {done && words.done && <span className="er-visually-hidden"> ({words.done})</span>}
                {passed && (track.skippedNotDone ? words.not_done : words.skipped) && (
                  <span className="er-visually-hidden"> ({track.skippedNotDone ? words.not_done : words.skipped})</span>
                )}
                {!done && !now && !passed && words.next && <span className="er-visually-hidden"> ({words.next})</span>}
                {i === 0 && now && ahead > 0 && (
                  <span className="er-ghosts" aria-hidden="true" data-testid="ghost-pills">
                    {Array.from({ length: Math.min(ahead, 4) }, (_, k) => (
                      <span key={k} className="er-ghost" />
                    ))}
                  </span>
                )}
              </a>
            </li>
          );
        })}
      </ol>
      {settled && track.tone !== "closed" && <TrackToken track={track} events={events} />}
    </nav>
  );
}

const CAPTION: Partial<Record<StatusEvent["type"], { type: string; band: number }>> = {
  received: { type: "received", band: 1 },
  planned: { type: "split", band: 1 },
  queued: { type: "queued", band: 2 },
  work_claimed: { type: "claimed", band: 2 },
  work_submitted: { type: "submitted", band: 2 },
  check_refused: { type: "refused", band: 3 },
  check_claimed: { type: "rclaimed", band: 3 },
  check_approved: { type: "approved", band: 3 },
  check_sent_back: { type: "sentback", band: 3 },
  signoff_required: { type: "signoff", band: 4 },
  delivered: { type: "ready", band: 4 },
  published: { type: "ready", band: 4 },
  decided: { type: "decision", band: 4 },
  library_added: { type: "library", band: 4 },
};

/** "What has happened", newest first: one plain sentence per recorded fact, with its caption name for the film. */
export function plainHappened(rawEvents: StatusEvent[], facts: Facts, words: PlainWords): { at: number | null; text: string; type: StatusEvent["type"] }[] {
  const events = rawEvents.map(plainEvent);
  const h = words.happened;
  const many = facts.parts.length > 1;
  const label = (n: number | undefined) => {
    const part = facts.parts.find((p) => p.plan.part === n);
    return many && part ? `${words.kind[kindOf(part)]}: ` : "";
  };
  const remade = new Set<number>();
  const readied = new Set<string>();
  // A library answer since the last reopen: a reopen then says the answer didn't fit.
  let reusedSince = false;
  const rows: { at: number | null; text: string; type: StatusEvent["type"] }[] = [];
  for (const [index, event] of events.entries()) {
    if (!(event.receipt || event.ref)) continue;
    const n = event.part ?? 0;
    const again = remade.has(n);
    const push = (text: string | undefined) => text && rows.push({ at: event.at ?? null, text: label(event.part) + text, type: event.type });
    switch (event.type) {
      case "received":
        push(h.received);
        break;
      case "queued": {
        if (event.summary?.next_at) {
          push(fill(h.scheduled, { time: when(event.summary.next_at) }));
          break;
        }
        const place = event.part ? (event.places?.[String(event.part)] ?? event.place) : event.place;
        if (place) push(place === 1 ? h.queued_next : fill(h.queued, { nth: ordinal(place) }));
        break;
      }
      case "plan_claimed":
        // The planner claims the request once more to close it: a true step, in the words for what it did.
        if (events[index + 1]?.type === "closed") {
          push((byEranos(event) && h.plan_claimed_close_eranos) || h.plan_claimed_close || h.plan_claimed);
          break;
        }
        push(byEranos(event) && h.plan_claimed_eranos ? h.plan_claimed_eranos : h.plan_claimed);
        break;
      case "planned":
        push((event.parts ?? []).some((part) => part.route === "reuse_check") ? (h.planned_reuse_check ?? h.planned) : h.planned);
        break;
      case "blocked":
        push(fill(h.blocked, { reason: event.reason ?? "" }));
        break;
      case "work_claimed": {
        // Only a claim marked as an outside volunteer is credited to a volunteer; an unmarked one is an AI worker.
        const eranos = byEranos(event);
        const volunteer = outsideVolunteer(event);
        push(
          again
            ? volunteer ? (h.work_claimed_changes_volunteer ?? h.work_claimed_changes) : h.work_claimed_changes
            : eranos ? h.work_claimed_eranos : volunteer ? (h.work_claimed_volunteer ?? h.work_claimed) : h.work_claimed,
        );
        break;
      }
      case "work_released": {
        const reason = cleanPlainReason(event.reason);
        push(reason && h.work_released_reason ? fill(h.work_released_reason, { reason }) : h.work_released);
        break;
      }
      case "work_submitted":
        push(again ? h.work_submitted_changes : h.work_submitted);
        break;
      case "check_refused":
        push(h.check_refused);
        break;
      case "check_claimed": {
        const eranos = byEranos(event);
        const volunteer = outsideVolunteer(event);
        push(
          again
            ? eranos ? (h.check_claimed_changes_eranos ?? h.check_claimed_changes) : volunteer ? (h.check_claimed_changes_volunteer ?? h.check_claimed_changes) : h.check_claimed_changes
            : eranos ? (h.check_claimed_eranos ?? h.check_claimed) : volunteer ? (h.check_claimed_volunteer ?? h.check_claimed) : h.check_claimed,
        );
        break;
      }
      case "check_sent_back":
        push(h.check_sent_back);
        break;
      case "check_approved":
      case "delivered":
      case "published": {
        if (event.summary?.reused) {
          reusedSince = true;
          push(h.reused);
          break;
        }
        const keyFor = `${n}:${again ? "again" : "first"}`;
        if (readied.has(keyFor)) break;
        readied.add(keyFor);
        push(again ? h.ready_changes : h.ready);
        break;
      }
      case "signoff_required":
        push(h.signoff_required);
        break;
      case "reopened":
        push(reusedSince ? h.reopened : event.reason && h.reopened_reason ? fill(h.reopened_reason, { reason: event.reason }) : h.reopened_plain);
        reusedSince = false;
        break;
      case "reuse_checked":
        push(event.verdict === "fits" ? h.reuse_fits : h.reuse_does_not_fit);
        break;
      case "decided":
        if (event.choice === "changes") remade.add(n);
        push(event.choice === "use" ? h.decided_use : event.choice === "changes" ? h.decided_changes : h.decided_dont);
        break;
      case "library_added":
        push(h.library_added);
        break;
      case "withdrawn":
        push(h.withdrawn);
        break;
      case "closed": {
        const plannedParts = facts.parts.length > 0;
        const anyReady = readied.size > 0 || facts.parts.some((p) => p.check === "approved");
        push(plannedParts && !anyReady ? (h.closed_unfinished ?? h.closed) : h.closed);
        break;
      }
      default:
        break;
    }
  }
  return rows.reverse();
}

/** When a part started waiting for a volunteer: its plan, its place in line, a release or a request for changes. */
function waitingSince(events: StatusEvent[], part: number): number | null {
  let since: number | null = null;
  for (const event of events) {
    if (!(event.receipt || event.ref) || event.at == null) continue;
    if (event.type === "planned" || ((event.type === "queued" || event.type === "work_released") && event.part === part)) since = event.at;
    if (event.type === "decided" && event.part === part && event.choice === "changes") since = event.at;
  }
  return since;
}

/** The band each `#step-*` anchor opens. */
const BAND_FOR_HASH: Record<string, number> = { "#step-split": 1, "#step-build": 2, "#step-review": 3, "#step-ready": 4 };

/**
 * The four bands as an accordion (owner, Nov 1): the current step is open; when a recorded fact moves the request
 * on, the finished step folds to its one-line status and the next one opens. A section the person opened by hand
 * stays open, and an anchor (a station, or a `#step-*` link) opens its section and scrolls to it.
 */
function useBands(current: number) {
  const hash = useHash();
  const fromHash = BAND_FOR_HASH[typeof window === "undefined" ? "" : window.location.hash];
  const byHand = useRef<Set<number>>(new Set(fromHash ? [fromHash] : []));
  const [open, setOpen] = useState<Set<number>>(() => new Set([current, ...byHand.current]));
  const [byEvent, setByEvent] = useState<number | null>(null);
  const shown = useRef(current);
  useEffect(() => {
    if (current === shown.current) return;
    shown.current = current;
    setOpen(new Set([current, ...byHand.current]));
    setByEvent(current);
  }, [current]);
  const reveal = (n: number) => {
    byHand.current.add(n);
    setOpen((was) => (was.has(n) ? was : new Set([...was, n])));
    // After the section opens, bring it to the top, clear of the sticky track (its scroll-margin-top).
    window.requestAnimationFrame(() => document.getElementById(BAND_IDS[n - 1] ?? "")?.scrollIntoView({ block: "start" }));
  };
  useEffect(() => {
    const n = BAND_FOR_HASH[hash];
    if (n) reveal(n);
  }, [hash]);
  const toggle = (n: number) =>
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(n)) {
        next.delete(n);
        byHand.current.delete(n);
      } else {
        next.add(n);
        byHand.current.add(n);
      }
      return next;
    });
  return { open, byEvent, toggle, reveal };
}

function Band({
  n,
  title,
  state,
  status,
  open,
  byEvent,
  onToggle,
  children,
}: {
  n: number;
  title: string;
  state: StageState;
  status: string;
  open: boolean;
  byEvent: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section
      id={BAND_IDS[n - 1]}
      className={`er-panel er-rq-band er-rq-band-${state}`}
      data-band={n}
      data-state={state}
      data-open={open}
      aria-labelledby={`band-${n}`}
    >
      <h2 id={`band-${n}`} className="er-panel-title er-band-head">
        <button type="button" className="er-band-toggle" aria-expanded={open} aria-controls={`band-${n}-body`} onClick={onToggle} data-testid={`band-toggle-${n}`}>
          <span className="er-band-n" aria-hidden="true">
            {n}
          </span>
          <span className="er-band-title">{title}</span>
          <span className="er-band-status" data-testid={`band-status-${n}`}>
            {status}
          </span>
          <span className="er-band-chevron" aria-hidden="true" />
        </button>
      </h2>
      <div id={`band-${n}-body`} className="er-band-body" hidden={!open} data-by-event={byEvent} role="region" aria-labelledby={`band-${n}`} tabIndex={0}>
        {children}
      </div>
    </section>
  );
}

export function PlainStatus({
  summary,
  facts,
  events: rawEvents,
  words,
  clock,
  shareUrl,
  routeId,
  requester,
  settled = true,
  requestText,
}: {
  /** The request's own words, for "Ask again"; never holds the private key. */
  requestText?: string | null;
  /** False until a live page has read the request's first real snapshot: the track shows no token before then. */
  settled?: boolean;
  summary: PlainSummary;
  facts: Facts;
  events: StatusEvent[];
  words: PlainWords;
  clock: (at: number) => string;
  shareUrl: string;
  routeId: string;
  requester: boolean;
}) {
  const events = rawEvents.map(plainEvent);
  const [all, setAll] = useState(false);
  const [shared, setShared] = useState(false);
  const happened = plainHappened(events, facts, words);
  const shown = all ? happened : happened.slice(0, 5);
  const parts = facts.parts;
  const many = parts.length > 1;
  const b = words.bands;
  const planned = facts.plan === "done" && parts.length > 0;
  // Answered from the library (F-UI-STALE-001): each step says so, from the request's own record.
  const candidate = !facts.reused && facts.reuseCandidate && facts.reuseCheck?.verdict !== "does_not_fit" && !facts.closed ? facts.reuseCandidate : undefined;
  const reuse = facts.reused ?? candidate;
  // Closed with nothing delivered: say what happened and what to do, from the request's own record.
  const nothingReady = !parts.some((p) => p.check === "approved" || p.decide === "yourturn" || p.decide === "decided");
  const noResult = facts.closed && nothingReady && !facts.withdrawn && !facts.blocked && !facts.reused && words.no_result ? words.no_result : null;
  const cause = noResultCause(rawEvents);
  // A process no ready class fits is looked up as public information instead: the note says so.
  const noClass = parts.some((p) => p.plan.output_type === "process" && p.plan.route === "public-only");
  const noResultWhy = !noResult
    ? ""
    : noClass && noResult.why_no_process_class
      ? noResult.why_no_process_class
      : cause.tries === 0
      ? noResult.why_never_tried
      : cause.sources
        ? cause.tries === 1
          ? noResult.why_no_sources_one
          : fill(noResult.why_no_sources, { n: cause.tries })
        : cause.tries === 1
          ? noResult.why_other_one
          : fill(noResult.why_other, { n: cause.tries });
  const askAgainText = withoutOwnLabel(requestText);
  const reusedHref = facts.reused ? sourceHref({ type: "delivered", result_id: facts.reused.id, ref: facts.reused.ref }) : null;

  // Each new recorded fact is announced once for the film frame (the board's onEvent): its caption name, band and line.
  const announced = useRef(happened.length);
  useEffect(() => {
    const fresh = happened.length - announced.current;
    announced.current = happened.length;
    if (fresh <= 0) return;
    for (const row of happened.slice(0, fresh).reverse()) {
      const caption = CAPTION[row.type];
      if (!caption) continue;
      window.dispatchEvent(new CustomEvent("eranos:status-event", { detail: { n: happened.length, type: caption.type, band: caption.band, text: row.text } }));
    }
  }, [happened]);

  async function share() {
    try {
      await navigator.clipboard.writeText(fill(words.share_text, { url: shareUrl }));
      setShared(true);
      window.setTimeout(() => setShared(false), 2400);
    } catch {
      setShared(false);
    }
  }

  const tagFor = (part: Part, index: number): string => {
    const t = words.tags;
    if (index === 0) return facts.plan === "done" ? t.made : t.not_yet;
    if (changing(part)) return t.changing;
    if (part.check === "approved") return t.checked;
    if (part.work === "done") return t.made;
    return t.not_yet;
  };
  const stripState = (n: number): StageState => summary.bands[n - 1] ?? "upcoming";
  const resultPage = (n: number) => `/requests/${encodeURIComponent(routeId)}/result?part=${n}`;
  // The current step: the first band in progress, else the first one not done, or the last once everything is.
  const nowBand = summary.bands.findIndex((state) => state === "now");
  const openBand = summary.bands.findIndex((state) => state !== "done");
  // A library answer opens on its answer (step 4), or on step 3 while the check of its fit is still to come.
  const current = reuse ? (summary.bands[2] === "now" ? 3 : 4) : nowBand >= 0 ? nowBand + 1 : openBand >= 0 ? openBand + 1 : 4;
  const signoff = parts.some((p) => p.decide === "person") && !parts.some((p) => p.decide === "yourturn");
  const bands = useBands(current);
  // Each band's one-line, present-tense status, shown in its header whether it is open or folded.
  const st = b.status;
  const lastAt = (types: StatusEvent["type"][]) => [...events].reverse().find((e) => types.includes(e.type) && e.at)?.at ?? null;
  const doneLine = (at: number | null) => (at ? fill(st.done, { time: clock(at) }) : st.done_untimed);
  const anyChecking = parts.some((p) => p.check === "working");
  const sentBack = parts.some((p) => p.check === "sent_back");
  const openStatus = [
    stripState(1) === "done" ? doneLine(lastAt(["planned"])) : stripState(1) === "now" ? st.sorting : st.upcoming,
    stripState(2) === "done"
      ? doneLine(lastAt(["work_submitted"]))
      : stripState(2) === "now"
        ? parts.some((p) => p.work === "working")
          ? st.working
          : st.waiting_helper
        : st.upcoming,
    stripState(3) === "done"
      ? doneLine(lastAt(["check_approved"]))
      : stripState(3) === "now"
        ? sentBack
          ? st.sent_back
          : anyChecking
            ? st.checking
            : st.waiting_check
        : st.upcoming,
    stripState(4) === "done"
      ? doneLine(lastAt(["decided", "library_added"]))
      : signoff
        ? st.signoff
        : stripState(4) === "now"
          ? requester
            ? st.your_turn
            : st.their_turn
          : st.upcoming,
  ];
  const fitCheck = facts.reuseCheck;
  const bandStatus = reuse
    ? [
        st.reused_sorted ?? st.done_untimed,
        candidate ? (st.reuse_made_pending ?? st.reused_made ?? st.done_untimed) : (st.reused_made ?? st.done_untimed),
        fitCheck?.verdict === "fits"
          ? fitCheck.at
            ? fill(st.reuse_fits ?? st.done, { time: clock(fitCheck.at) })
            : (st.reuse_fits_untimed ?? st.done_untimed)
          : fitCheck?.verdict === "does_not_fit"
            ? (st.reuse_does_not_fit ?? st.closed ?? "")
            : facts.closed
              ? (st.reuse_unchecked ?? st.closed ?? "")
              : candidate
                ? (st.reuse_checking ?? st.checking)
                : (st.reuse_waiting_check ?? st.waiting_check),
        !facts.reused
          ? st.upcoming
          : reuse.at
            ? fill(st.reused_ready ?? st.done, { time: clock(reuse.at) })
            : (st.reused_ready ?? st.done_untimed),
      ]
    : openStatus.map((line, i) => (stripState(i + 1) === "closed" ? (st.closed ?? line) : line));
  const bandProps = (n: number) => ({
    status: bandStatus[n - 1] ?? "",
    open: bands.open.has(n),
    byEvent: bands.byEvent === n,
    onToggle: () => bands.toggle(n),
  });

  return (
    <div className="er-plain" data-testid="plain-status">
      <RequestTrack
        track={summary.track}
        events={events}
        words={words.track}
        label={words.stages_label}
        settled={settled}
        requester={requester}
        onStation={(n) => bands.reveal(n)}
        ahead={parts.some((p) => !p.workAgent && p.work !== "done") ? Math.max(0, (parts.find((p) => !p.workAgent && p.work !== "done")?.place ?? 1) - 1) : 0}
      />
      <p className="er-visually-hidden" aria-live="polite" data-testid="track-live">
        {(happened.find((row) => row.type !== "signoff_required") ?? happened[0])?.text ?? ""}
      </p>
      {noResult && (
        <section className="er-panel er-no-result" aria-labelledby="no-result-title" data-testid="no-result">
          <h2 id="no-result-title">{noResult.title}</h2>
          <p data-testid="no-result-why">
            {noResult.nothing_delivered} {noResultWhy}
          </p>
          <h3>{noResult.can_do_title}</h3>
          <ul>
            {noResult.can_do.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <AppLink
            to={askAgainText ? `/nonprofits?q=${encodeURIComponent(askAgainText)}` : "/nonprofits"}
            className="er-btn-primary"
            data-testid="no-result-again"
          >
            {noResult.again}
          </AppLink>
        </section>
      )}
      {facts.reuseRejected && !facts.reused && words.reuse_rejected_note && (
        <p className="er-small er-reopened" data-testid="reuse-rejected-note">
          {words.reuse_rejected_note}
        </p>
      )}
      {facts.reopened && (
        <p className="er-small er-reopened" data-testid="reopened-note">
          {facts.reuseUndone
            ? words.reopened_note
            : facts.reopened.reason && words.reopened_note_reason
              ? fill(words.reopened_note_reason, { reason: facts.reopened.reason })
              : words.reopened_note_plain}
        </p>
      )}

      <Band n={1} title={b.sorted.title} state={stripState(1)} {...bandProps(1)}>
        {reuse ? (
          <p className="er-band-line" data-testid="reused-sorted">
            {b.reused?.sorted}
          </p>
        ) : (
          <>
            {facts.received?.at != null && <p className="er-band-ok">{fill(b.sorted.checked, { time: clock(facts.received.at) })}</p>}
            {planned ? (
              <ul className="er-band-list">
                {parts.map((part) => (
                  <li key={part.plan.part}>
                    <strong>{kindOf(part) === "process" ? b.sorted.process : b.sorted.information}</strong>
                    <span className="er-small">{part.plan.text}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="er-small">{b.sorted.waiting}</p>
            )}
          </>
        )}
      </Band>

      <Band n={2} title={reuse ? (b.made.title_reused ?? b.made.title_done) : stripState(2) === "done" ? b.made.title_done : b.made.title_now} state={stripState(2)} {...bandProps(2)}>
        {reuse ? (
          <p className="er-band-line" data-testid="reused-made">
            {b.reused?.made}
          </p>
        ) : (
          <>
            {!planned && <p className="er-small">{b.made.waiting.replace(/ · .*$/, "")}</p>}
            {parts.map((part) => {
              const n = part.plan.part;
              const agent = part.workAgent;
              const done = part.work === "done";
              const waitingForVolunteer = !agent && !done && part.work !== "held";
              const since = waitingForVolunteer ? waitingSince(events, n) : null;
              return (
                <div key={n} className="er-band-part" data-part={n}>
                  {many && <h3 className="er-making-kind">{words.kind[kindOf(part)]}</h3>}
                  {agent && (
                    <p className="er-helper" data-testid={`helper-${n}`}>
                      <strong>{agent.dedicated ? b.made.helper_eranos : agent.volunteer ? b.made.helper_volunteer : b.made.helper_worker}</strong>{" "}
                      {agent.claimedAt != null && fill(agent.dedicated ? b.made.picked_eranos : b.made.picked, { time: clock(agent.claimedAt) })}
                    </p>
                  )}
                  {(() => {
                    const tries = events.filter((e) => e.part === n && (e.type === "work_claimed" || e.type === "work_released"));
                    const last = tries.at(-1);
                    if (!last || last.type !== "work_released" || !last.reason || done) return null;
                    const retry = last.summary?.attempt && last.summary.max_attempts ? fill(b.made.retry_count, { n: last.summary.attempt, m: last.summary.max_attempts }) : b.made.retry;
                    return (
                      <p className="er-band-failed" data-testid={`failed-${n}`}>
                        {fill(b.made.failed, { reason: shortReason(last.reason) })} {retry}
                      </p>
                    );
                  })()}
                  {waitingForVolunteer && (
                    <p className="er-small" data-testid={`waiting-${n}`}>
                      {fill(b.made.waiting, { nth: ordinal(part.place ?? 1) })}{" "}
                      {since != null && fill(b.made.fallback, { time: clock(since + FALLBACK_SECONDS) })}
                    </p>
                  )}
                  <ul className="er-making" data-testid={`making-${n}`}>
                    {words.making[kindOf(part)].map((item, index) => (
                      <li key={item}>
                        <span>{item}</span>
                        <span className="er-tag">{tagFor(part, index)}</span>
                      </li>
                    ))}
                  </ul>
                  {done && (
                    <p className="er-small er-band-ok">
                      {b.made.recorded}
                      {b.made.models_link && b.made.models_href && (
                        <>
                          {" "}
                          <a href={b.made.models_href}>{b.made.models_link}</a>
                        </>
                      )}
                    </p>
                  )}
                </div>
              );
            })}
          </>
        )}
      </Band>

      <Band n={3} title={reuse ? (b.checked.title_reused ?? b.checked.title) : parts.some((p) => p.checkAgent?.dedicated) && b.checked.title_eranos ? b.checked.title_eranos : b.checked.title} state={stripState(3)} {...bandProps(3)}>
        {reuse ? (
          <p className="er-band-line" data-testid="reused-checked">
            {fitCheck?.verdict === "fits"
              ? [b.reused?.fits, fitCheck.who && b.reused?.fits_by ? fill(b.reused.fits_by, { who: fitCheck.who, model: fitCheck.model ?? b.reused.no_model ?? "" }) : ""].filter(Boolean).join(" ")
              : fitCheck?.verdict === "does_not_fit"
                ? b.reused?.does_not_fit
                : candidate
                  ? b.reused?.checking
                  : b.reused?.unchecked}
          </p>
        ) : (
          <>
            <p className="er-small">{b.checked.rule}</p>
            {parts.map((part) => {
              const n = part.plan.part;
              const refused = events.some((e) => e.type === "check_refused" && e.part === n && (e.receipt || e.ref));
              const notes = part.checkEvidence?.reason ? 1 : 0;
              const findings = events.filter((e) => e.type === "check_sent_back" && e.part === n).at(-1)?.findings?.length ?? notes;
              const line =
                part.check === "approved"
                  ? b.checked.done
                  : part.check === "sent_back"
                    ? findings > 1
                      ? fill(b.checked.sent_back_many, { n: findings })
                      : b.checked.sent_back_one
                    : part.check === "working"
                      ? part.checkAgent?.dedicated && b.checked.checking_eranos
                        ? b.checked.checking_eranos
                        : part.checkAgent?.volunteer && b.checked.checking_volunteer
                          ? b.checked.checking_volunteer
                          : b.checked.checking
                      : part.work === "done"
                        ? b.checked.waiting
                        : b.checked.upcoming;
              return (
                <p key={n} className="er-band-line" data-testid={`check-${n}`}>
                  {many && <strong>{words.kind[kindOf(part)]}: </strong>}
                  {refused && <span className="er-band-blocked">{b.checked.blocked} · </span>}
                  {line}
                </p>
              );
            })}
          </>
        )}
      </Band>

      <Band n={4} title={stripState(4) === "done" && b.ready.title_done ? b.ready.title_done : requester ? b.ready.title : b.ready.title_public} state={stripState(4)} {...bandProps(4)}>
        {reuse ? (
          <p className="er-band-line" data-testid="reused-ready">
            {facts.reused ? b.ready.reused : b.ready.upcoming}{" "}
            {reusedHref && (
              <a href={reusedHref} className="er-text-link">
                {b.ready.reused_link}
              </a>
            )}
          </p>
        ) : (
          <>
            {(() => {
              const next = events.filter((e) => e.type === "queued" && e.summary?.next_at && (e.receipt || e.ref)).at(-1)?.summary?.next_at;
              return next ? (
                <p className="er-small" data-testid="next-run">
                  {fill(b.ready.next_run, { time: when(next) })}
                </p>
              ) : null;
            })()}
            {parts.some((p) => p.decide === "yourturn" || p.decide === "decided") ? (
              <>
                <div className="er-ready-cards">
                  {parts
                    .filter((p) => p.decide === "yourturn" || p.decide === "decided")
                    .map((part) => (
                      <div key={part.plan.part} className="er-ready-card" data-testid={`ready-${part.plan.part}`}>
                        <strong>{kindOf(part) === "process" ? b.ready.process : b.ready.information}</strong>
                        <AppLink to={resultPage(part.plan.part)} className="er-text-link">
                          {kindOf(part) === "process" ? b.ready.open_process : b.ready.open_information}
                        </AppLink>
                      </div>
                    ))}
                </div>
                {parts.map((part) => {
                  const reused = events.filter((e) => e.part === part.plan.part && (e.type === "delivered" || e.type === "published") && e.summary?.reused).at(-1);
                  if (!reused) return null;
                  const href = sourceHref(reused);
                  return (
                    <p key={`reused-${part.plan.part}`} data-testid={`reused-${part.plan.part}`}>
                      {b.ready.reused}{" "}
                      {href &&
                        (href.startsWith("/catalog/") ? (
                          <AppLink to={href} className="er-text-link">
                            {b.ready.reused_link}
                          </AppLink>
                        ) : (
                          <a href={href} className="er-text-link">
                            {b.ready.reused_link}
                          </a>
                        ))}
                    </p>
                  );
                })}
                {requester && summary.yourTurn && (
                  <p>
                    <strong>{b.ready.decide}</strong>{" "}
                    <AppLink to={resultPage(parts.find((p) => p.decide === "yourturn")?.plan.part ?? 1)} className="er-text-link">
                      {b.ready.decide_link}
                    </AppLink>
                  </p>
                )}
                {parts.some((p) => p.library) && (
                  <p className="er-small" data-testid="ready-library">
                    <strong>{b.ready.library_title}:</strong> {b.ready.library_added}{" "}
                    <AppLink to={`/library?request=${encodeURIComponent(routeId)}`} className="er-text-link">
                      {b.ready.library_link}
                    </AppLink>{" "}
                    <a href={AGORA_HOW_IT_WORKS_URL} className="er-text-link">
                      {b.ready.library_how}
                    </a>
                  </p>
                )}
              </>
            ) : (
              <p className="er-small">{b.ready.upcoming}</p>
            )}
          </>
        )}
      </Band>

      {summary.waiting && (
        <section className="er-panel er-share" data-testid="share-request">
          <p>{words.share_lead}</p>
          <button type="button" className="er-btn-secondary" onClick={() => void share()}>
            {shared ? words.shared : words.share}
          </button>
        </section>
      )}

      <section className="er-panel" aria-labelledby="happened-title">
        <h2 id="happened-title" className="er-panel-title">
          {words.happened_title}
        </h2>
        <ol className="er-happened" data-testid="plain-happened">
          {shown.map((row, index) => (
            <li key={`${index}-${row.text}`}>
              {row.at !== null && <span className="er-small er-happened-time">{clock(row.at)}</span>}
              <span>{row.text}</span>
            </li>
          ))}
        </ol>
        {happened.length > 5 && !all && (
          <button type="button" className="er-text-link er-link-button" onClick={() => setAll(true)}>
            {fill(words.happened_more, { n: happened.length })}
          </button>
        )}
      </section>
    </div>
  );
}
