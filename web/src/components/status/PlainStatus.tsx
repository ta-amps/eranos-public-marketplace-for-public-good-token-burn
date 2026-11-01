import { useEffect, useRef, useState } from "react";

import { AGORA_HOW_IT_WORKS_URL } from "../../lib/marketplace";
import { fill, type PlainWords } from "../../lib/nouns";
import type { Facts } from "../../lib/status/derive";
import { ordinal } from "../../lib/status/estimate";
import type { StatusEvent } from "../../lib/status/types";
import { AppLink } from "../../router";

/**
 * The request page's plain view (RequestStatusPage v6, Claude Design 20:15): a progress strip and four bands, in
 * plain words. No volunteer names, ids or receipts; those stay in the technical view. Every line is read from the
 * same recorded facts as the diagram, so the two views never disagree.
 */

type StageState = "done" | "now" | "upcoming";
type Kind = "process" | "information";
type Part = Facts["parts"][number];

/** A task nobody claims within this time goes to one of Eranos's own workers ("volunteers first"). */
const FALLBACK_SECONDS = 90;

function kindOf(part: Part): Kind {
  const declared = part.plan.output_type;
  if (declared === "process" || declared === "information") return declared;
  return part.plan.route === "private-files" ? "process" : "information";
}

/** A part is being remade after the requester asked for changes, until a new check approves it. */
function changing(part: Part): boolean {
  return part.decision?.choice === "changes" && part.decide !== "yourturn";
}

export interface PlainSummary {
  strip: { label: string; state: StageState }[];
  chip: string;
  waiting: boolean;
  yourTurn: boolean;
}

export function plainSummary(facts: Facts, words: PlainWords, every: string, requester = true): PlainSummary {
  const parts = facts.parts;
  const planned = facts.plan === "done" && parts.length > 0;
  const anyWorking = parts.some((p) => p.work === "working");
  const allMade = planned && parts.every((p) => p.work === "done");
  const anyChecking = parts.some((p) => p.check === "working");
  const allChecked = planned && parts.every((p) => p.check === "approved");
  const sentBack = parts.some((p) => p.check === "sent_back");
  const waitingCheck = parts.some((p) => p.work === "done" && p.check !== "approved" && p.check !== "working" && p.check !== "sent_back");
  const yourTurn = parts.some((p) => p.decide === "yourturn");
  const allDecided = planned && parts.every((p) => p.decide === "decided");
  const used = parts.some((p) => p.decision?.choice === "use");
  const inLibrary = parts.some((p) => p.library);
  const remaking = parts.some(changing);
  const state = (done: boolean, now: boolean): StageState => (done ? "done" : now ? "now" : "upcoming");
  const labels = words.strip;
  const strip = [
    { label: labels[0] ?? "", state: "done" as StageState },
    { label: labels[1] ?? "", state: state(planned, !planned) },
    { label: labels[2] ?? "", state: state(allMade && !remaking, planned) },
    { label: labels[3] ?? "", state: state(allChecked && !remaking, anyChecking || waitingCheck || sentBack) },
    { label: requester ? (labels[4] ?? "") : words.strip_ready_public, state: state(allDecided, yourTurn) },
    { label: labels[5] ?? "", state: state(inLibrary, false) },
  ];

  const c = words.chip;
  const chip = facts.withdrawn
    ? c.withdrawn
    : facts.blocked
      ? c.blocked
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
  const waiting = !facts.withdrawn && !facts.blocked && !yourTurn && !allDecided && !anyWorking && !anyChecking;
  return { strip, chip, waiting, yourTurn };
}

/** The board's caption names for the film frame (RequestStatusPage onEvent), from the recorded event types. */
/** Ids for the strip steps; the judge tour links to #step-ready. */
const STEP_IDS = ["sent", "sorted", "made", "checked", "ready", "library"];

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
export function plainHappened(events: StatusEvent[], facts: Facts, words: PlainWords): { at: number | null; text: string; type: StatusEvent["type"] }[] {
  const h = words.happened;
  const many = facts.parts.length > 1;
  const label = (n: number | undefined) => {
    const part = facts.parts.find((p) => p.plan.part === n);
    return many && part ? `${words.kind[kindOf(part)]}: ` : "";
  };
  const remade = new Set<number>();
  const readied = new Set<string>();
  const rows: { at: number | null; text: string; type: StatusEvent["type"] }[] = [];
  for (const event of events) {
    if (!(event.receipt || event.ref)) continue;
    const n = event.part ?? 0;
    const again = remade.has(n);
    const push = (text: string | undefined) => text && rows.push({ at: event.at ?? null, text: label(event.part) + text, type: event.type });
    switch (event.type) {
      case "received":
        push(h.received);
        break;
      case "queued": {
        const place = event.part ? (event.places?.[String(event.part)] ?? event.place) : event.place;
        if (place) push(place === 1 ? h.queued_next : fill(h.queued, { nth: ordinal(place) }));
        break;
      }
      case "plan_claimed":
        push(h.plan_claimed);
        break;
      case "planned":
        push(h.planned);
        break;
      case "blocked":
        push(fill(h.blocked, { reason: event.reason ?? "" }));
        break;
      case "work_claimed": {
        const eranos = event.dedicated ?? /^eranos[-_.\s]/i.test(event.worker ?? "");
        push(again ? h.work_claimed_changes : eranos ? h.work_claimed_eranos : h.work_claimed);
        break;
      }
      case "work_released":
        push(h.work_released);
        break;
      case "work_submitted":
        push(again ? h.work_submitted_changes : h.work_submitted);
        break;
      case "check_refused":
        push(h.check_refused);
        break;
      case "check_claimed":
        push(again ? h.check_claimed_changes : h.check_claimed);
        break;
      case "check_sent_back":
        push(h.check_sent_back);
        break;
      case "check_approved":
      case "delivered":
      case "published": {
        const keyFor = `${n}:${again ? "again" : "first"}`;
        if (readied.has(keyFor)) break;
        readied.add(keyFor);
        push(again ? h.ready_changes : h.ready);
        break;
      }
      case "signoff_required":
        push(h.signoff_required);
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
      case "closed":
        push(h.closed);
        break;
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

function Band({ n, title, state, children }: { n: number; title: string; state: StageState; children: React.ReactNode }) {
  return (
    <section className={`er-panel er-band er-band-${state}`} data-band={n} data-state={state} aria-labelledby={`band-${n}`}>
      <h2 id={`band-${n}`} className="er-panel-title">
        <span className="er-band-n" aria-hidden="true">
          {n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function PlainStatus({
  summary,
  facts,
  events,
  words,
  clock,
  shareUrl,
  routeId,
  requester,
}: {
  summary: PlainSummary;
  facts: Facts;
  events: StatusEvent[];
  words: PlainWords;
  clock: (at: number) => string;
  shareUrl: string;
  routeId: string;
  requester: boolean;
}) {
  const [all, setAll] = useState(false);
  const [shared, setShared] = useState(false);
  const happened = plainHappened(events, facts, words);
  const shown = all ? happened : happened.slice(0, 5);
  const parts = facts.parts;
  const many = parts.length > 1;
  const b = words.bands;
  const planned = facts.plan === "done" && parts.length > 0;

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
  const stripState = (i: number) => summary.strip[i]?.state ?? "upcoming";
  const resultPage = (n: number) => `/requests/${encodeURIComponent(routeId)}/result?part=${n}`;

  return (
    <div className="er-plain" data-testid="plain-status">
      <ol className="er-strip" aria-label={words.stages_label}>
        {summary.strip.map((step, i) => (
          <li key={step.label} id={`step-${STEP_IDS[i]}`} className={`er-strip-step er-stage-${step.state}`} data-step={i} data-state={step.state}>
            <span className="er-stage-dot" aria-hidden="true" />
            <span>{step.label}</span>
          </li>
        ))}
      </ol>

      <Band n={1} title={b.sorted.title} state={stripState(1)}>
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
      </Band>

      <Band n={2} title={stripState(2) === "done" ? b.made.title_done : b.made.title_now} state={stripState(2)}>
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
                  <strong>{agent.dedicated ? b.made.helper_eranos : b.made.helper_volunteer}</strong>{" "}
                  {agent.claimedAt != null && fill(agent.dedicated ? b.made.picked_eranos : b.made.picked, { time: clock(agent.claimedAt) })}
                </p>
              )}
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
              {done && <p className="er-small er-band-ok">{b.made.recorded}</p>}
            </div>
          );
        })}
      </Band>

      <Band n={3} title={b.checked.title} state={stripState(3)}>
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
                  ? b.checked.checking
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
      </Band>

      <Band n={4} title={requester ? b.ready.title : b.ready.title_public} state={stripState(4)}>
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
