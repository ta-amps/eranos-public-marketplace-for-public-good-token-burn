import { useState } from "react";

import { fill, type PlainWords } from "../../lib/nouns";
import type { Facts } from "../../lib/status/derive";
import { ordinal } from "../../lib/status/estimate";
import type { StatusEvent } from "../../lib/status/types";

/**
 * The request page's plain view (Flow-Prototype step 3): six stages, what is being made, and what has happened, in
 * plain sentences. No volunteer names, ids or receipts; those stay in the technical view. Every line is read from
 * the same recorded facts as the diagram, so the two views never disagree.
 */

type StageState = "done" | "now" | "upcoming";
export interface PlainStage {
  id: "sent" | "line" | "made" | "checked" | "ready" | "shared";
  title: string;
  line: string;
  state: StageState;
}

type Kind = "process" | "information";
type Part = Facts["parts"][number];

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
  stages: PlainStage[];
  chip: string;
  waiting: boolean;
  yourTurn: boolean;
}

export function plainSummary(facts: Facts, words: PlainWords, clock: (at: number) => string, every: string): PlainSummary {
  const s = words.stages;
  const parts = facts.parts;
  const planned = facts.plan === "done" && parts.length > 0;
  const anyWorking = parts.some((p) => p.work === "working");
  const allMade = planned && parts.every((p) => p.work === "done");
  const anyChecking = parts.some((p) => p.check === "working");
  const allChecked = planned && parts.every((p) => p.check === "approved");
  const waitingCheck = parts.some((p) => p.work === "done" && p.check !== "approved" && p.check !== "working");
  const yourTurn = parts.some((p) => p.decide === "yourturn");
  const allDecided = planned && parts.every((p) => p.decide === "decided");
  const used = parts.some((p) => p.decision?.choice === "use");
  const inLibrary = parts.some((p) => p.library);
  const remaking = parts.some(changing);
  const sentAt = facts.received?.at ?? null;
  const pickedAt = facts.planEvidence?.at ?? facts.planAgent?.claimedAt ?? null;
  const place = facts.planPlace;

  const line: PlainStage =
    facts.plan === "waiting"
      ? {
          id: "line",
          title: s.line.title,
          state: "now",
          line: !place ? s.line.waiting : place === 1 ? s.line.next : place === 2 ? s.line.ahead_one : fill(s.line.ahead_many, { n: place - 1 }),
        }
      : { id: "line", title: s.line.title, state: "done", line: pickedAt ? fill(s.line.done, { time: clock(pickedAt) }) : s.line.done.replace(/ at \{time\}$/, "") };

  const made: PlainStage = !planned
    ? { id: "made", title: s.made.title, state: facts.plan === "working" ? "now" : "upcoming", line: facts.plan === "working" ? s.made.planning : s.made.upcoming }
    : allMade && !remaking
      ? { id: "made", title: s.made.title, state: "done", line: s.made.done }
      : { id: "made", title: s.made.title, state: "now", line: anyWorking ? (remaking ? s.made.changes : s.made.making) : s.made.between };

  const checked: PlainStage =
    allChecked && !remaking
      ? { id: "checked", title: s.checked.title, state: "done", line: s.checked.done }
      : anyChecking
        ? { id: "checked", title: s.checked.title, state: "now", line: s.checked.checking }
        : waitingCheck
          ? { id: "checked", title: s.checked.title, state: "now", line: s.checked.waiting }
          : { id: "checked", title: s.checked.title, state: "upcoming", line: s.checked.upcoming };

  const ready: PlainStage = allDecided
    ? { id: "ready", title: s.ready.title, state: "done", line: used ? s.ready.done : s.ready.decided }
    : yourTurn
      ? { id: "ready", title: s.ready.title, state: "now", line: s.ready.now }
      : { id: "ready", title: s.ready.title, state: "upcoming", line: s.ready.upcoming };

  const shared: PlainStage = inLibrary
    ? { id: "shared", title: s.shared.title, state: "done", line: s.shared.done }
    : { id: "shared", title: s.shared.title, state: "upcoming", line: s.shared.upcoming };

  const c = words.chip;
  const chip = facts.withdrawn
    ? c.withdrawn
    : facts.blocked
      ? c.blocked
      : yourTurn
        ? c.ready
        : allDecided
          ? used
            ? inLibrary
              ? every
                ? fill(c.in_use_regular, { every })
                : c.in_use
              : c.in_use_plain
            : c.not_used
          : remaking && anyWorking
            ? c.changes
            : anyChecking
              ? c.checking
              : waitingCheck
                ? c.waiting_check
                : anyWorking
                  ? c.making
                  : planned
                    ? c.waiting_volunteer
                    : facts.plan === "working"
                      ? c.planning
                      : c.in_line;

  const sent: PlainStage = { id: "sent", title: s.sent.title, state: "done", line: sentAt ? fill(s.sent.done, { time: clock(sentAt) }) : s.sent.title };
  const waiting = !facts.withdrawn && !facts.blocked && !yourTurn && !allDecided && !anyWorking && !anyChecking;
  return { stages: [sent, line, made, checked, ready, shared], chip, waiting, yourTurn };
}

/** "What has happened", newest first: one plain sentence per recorded fact. */
export function plainHappened(events: StatusEvent[], facts: Facts, words: PlainWords): { at: number | null; text: string }[] {
  const h = words.happened;
  const many = facts.parts.length > 1;
  const label = (n: number | undefined) => {
    const part = facts.parts.find((p) => p.plan.part === n);
    return many && part ? `${words.kind[kindOf(part)]}: ` : "";
  };
  const remade = new Set<number>();
  const readied = new Set<string>();
  const rows: { at: number | null; text: string }[] = [];
  for (const event of events) {
    if (!(event.receipt || event.ref)) continue;
    const n = event.part ?? 0;
    const again = remade.has(n);
    const push = (text: string | undefined) => text && rows.push({ at: event.at ?? null, text: label(event.part) + text });
    switch (event.type) {
      case "received":
        rows.push({ at: event.at ?? null, text: h.received });
        break;
      case "queued": {
        const place = event.part ? (event.places?.[String(event.part)] ?? event.place) : event.place;
        if (place) push(place === 1 ? h.queued_next : fill(h.queued, { nth: ordinal(place) }));
        break;
      }
      case "plan_claimed":
        rows.push({ at: event.at ?? null, text: h.plan_claimed });
        break;
      case "planned":
        rows.push({ at: event.at ?? null, text: h.planned });
        break;
      case "blocked":
        rows.push({ at: event.at ?? null, text: fill(h.blocked, { reason: event.reason ?? "" }) });
        break;
      case "work_claimed":
        push(again ? h.work_claimed_changes : h.work_claimed);
        break;
      case "work_released":
        push(h.work_released);
        break;
      case "work_submitted":
        push(again ? h.work_submitted_changes : h.work_submitted);
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
        rows.push({ at: event.at ?? null, text: h.withdrawn });
        break;
      case "closed":
        rows.push({ at: event.at ?? null, text: h.closed });
        break;
      default:
        break;
    }
  }
  return rows.reverse();
}

export function PlainStatus({
  summary,
  facts,
  events,
  words,
  clock,
  shareUrl,
}: {
  summary: PlainSummary;
  facts: Facts;
  events: StatusEvent[];
  words: PlainWords;
  clock: (at: number) => string;
  shareUrl: string;
}) {
  const [all, setAll] = useState(false);
  const [shared, setShared] = useState(false);
  const happened = plainHappened(events, facts, words);
  const shown = all ? happened : happened.slice(0, 5);
  const parts = facts.parts;
  const many = parts.length > 1;

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

  return (
    <div className="er-plain" data-testid="plain-status">
      <ol className="er-stages" aria-label={words.stages_label}>
        {summary.stages.map((stage) => (
          <li key={stage.id} className={`er-stage er-stage-${stage.state}`} data-stage={stage.id} data-state={stage.state}>
            <span className="er-stage-dot" aria-hidden="true" />
            <span className="er-stage-title">{stage.title}</span>
            <span className="er-stage-line">{stage.line}</span>
          </li>
        ))}
      </ol>

      {summary.waiting && (
        <section className="er-panel er-share" data-testid="share-request">
          <p>{words.share_lead}</p>
          <button type="button" className="er-btn-secondary" onClick={() => void share()}>
            {shared ? words.shared : words.share}
          </button>
        </section>
      )}

      <div className="er-plain-columns">
        <section className="er-panel" aria-labelledby="making-title">
          <h2 id="making-title" className="er-panel-title">
            {words.making_title}
          </h2>
          {parts.length === 0 ? (
            <ul className="er-making">
              <li>
                <span>{words.making.information[0]}</span>
                <span className="er-tag">{words.tags.not_yet}</span>
              </li>
            </ul>
          ) : (
            parts.map((part) => (
              <div key={part.plan.part}>
                {many && <h3 className="er-making-kind">{words.kind[kindOf(part)]}</h3>}
                <ul className="er-making" data-testid={`making-${part.plan.part}`}>
                  {words.making[kindOf(part)].map((item, index) => (
                    <li key={item}>
                      <span>{item}</span>
                      <span className="er-tag">{tagFor(part, index)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>

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
    </div>
  );
}
