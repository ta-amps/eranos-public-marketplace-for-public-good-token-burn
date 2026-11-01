import type { ReactNode, RefObject } from "react";

import { fill, type RequestStatusNoun } from "../../lib/nouns";
import type { ChipView, EdgeView, NodeState, NodeView, StatusView, StepView, LogRow } from "../../lib/status/derive";
import { shortReceipt, shortRequestId } from "../../lib/status/ids";
import type { QueueSnapshot } from "../../lib/status/types";
import { AppLink } from "../../router";
import { Icon } from "../Icon";

const STATE_ICON: Partial<Record<NodeState, string>> = {
  waiting: "circle-dashed",
  open: "circle-dashed",
  working: "circle-half",
  done: "check",
  approved: "circle-check",
  sent_back: "circle-x",
  stopped: "circle-x",
  person: "circle-alert",
  yourturn: "circle-alert",
  decided: "user-round-check",
  held: "info",
};

export function StateIcon({ state, size = 16 }: { state: NodeState; size?: number }) {
  const name = STATE_ICON[state];
  return name ? <Icon name={name} size={size} strokeWidth={2.25} /> : null;
}

/**
 * A recorded step as people read it (owner, Nov 1: no receipts or hashes on any page): a "Record" link to the public
 * record that holds it, or a short request id. A hash itself is never shown, not even in a title.
 */
export function Evidence({ value, words, href }: { value?: string; words: RequestStatusNoun; href?: string }) {
  if (!value) return null;
  const hash = /^[0-9a-f]{8,}$/i.test(value);
  const request = /^rq-r_[0-9a-f]{32}-[0-9a-z]+$/.test(value);
  const ref = /^(eranos\.[a-z_.]+)\/([A-Za-z0-9][A-Za-z0-9_.:-]*)/.exec(value);
  const link = href ?? (ref ? `/api/nouns/${ref[1]}/${encodeURIComponent(ref[2] ?? "")}` : undefined);
  if (request) return <span className="er-receipt">{shortRequestId(value)}</span>;
  if ((hash || ref) && link) {
    return (
      <a className="er-record-link" href={link}>
        {words.chips.record ?? "Record ↗"}
      </a>
    );
  }
  return hash || ref ? null : <span className="er-receipt">{value}</span>;
}

/** The lease ring: the share of the lease left, redrawn once a second while live, never animated. */
export function LeaseRing({ lease, now }: { lease?: { start: number; end: number }; now: number }) {
  const r = 9;
  const length = 2 * Math.PI * r;
  const left = lease ? Math.max(0, Math.min(1, (lease.end - now) / Math.max(1, lease.end - lease.start))) : 0;
  return (
    <span className="er-lease" aria-hidden="true">
      <svg width="22" height="22" viewBox="0 0 22 22">
        <circle className="er-lease-track" cx="11" cy="11" r={r} />
        {lease && (
          <circle
            className="er-lease-left"
            cx="11"
            cy="11"
            r={r}
            strokeDasharray={`${(left * length).toFixed(2)} ${length.toFixed(2)}`}
            transform="rotate(-90 11 11)"
          />
        )}
        <rect className="er-lease-bot" x="7" y="8" width="8" height="6" rx="1.5" />
      </svg>
    </span>
  );
}

function Node({ node, words }: { node: NodeView; words: RequestStatusNoun }) {
  return (
    <div
      className={`er-node er-node-${node.state} er-node-${node.kind}`}
      data-node={node.id}
      data-state={node.state}
      data-receipt={node.evidence ?? ""}
      data-record={node.record ?? ""}
      style={{ left: node.x, top: node.y, width: node.w, height: node.h, borderRadius: node.r }}
    >
      <StateIcon state={node.state} />
      <span className="er-node-text">
        <span>{node.label}</span>
        {node.sub && <span className="er-node-sub">{node.sub}</span>}
      </span>
      <span className="er-visually-hidden">
        {" "}
        ({words.states[node.state] ?? node.state})
      </span>
    </div>
  );
}

function Chip({ chip, now }: { chip: ChipView; now: number }) {
  const body: ReactNode =
    chip.kind === "link" && chip.href ? (
      <AppLink to={chip.href}>{chip.text}</AppLink>
    ) : (
      <span>{chip.text}</span>
    );
  return (
    <div className={`er-chip-node er-chip-node-${chip.kind}`} data-chip={chip.id} data-chip-kind={chip.kind} style={{ left: chip.x, top: chip.y }}>
      {chip.kind === "agent" && <LeaseRing lease={chip.lease} now={now} />}
      {body}
    </div>
  );
}

function Edge({ edge }: { edge: EdgeView }) {
  const horizontal = edge.y1 === edge.y2;
  const head = edge.head
    ? horizontal
      ? `M ${edge.x2 - 5} ${edge.y2 - 4} L ${edge.x2} ${edge.y2} L ${edge.x2 - 5} ${edge.y2 + 4}`
      : ""
    : "";
  // A part's first edge may bend from the plan's height down to its row.
  const d =
    edge.x1 !== edge.x2 && edge.y1 !== edge.y2
      ? `M ${edge.x1} ${edge.y1} L ${(edge.x1 + edge.x2) / 2} ${edge.y1} L ${(edge.x1 + edge.x2) / 2} ${edge.y2} L ${edge.x2} ${edge.y2}`
      : `M ${edge.x1} ${edge.y1} L ${edge.x2} ${edge.y2}`;
  const tail =
    edge.head && !horizontal ? `M ${edge.x2 - 5} ${edge.y2 - 4} L ${edge.x2} ${edge.y2} L ${edge.x2 - 5} ${edge.y2 + 4}` : head;
  return (
    <g className={edge.done ? "er-edge er-edge-done" : "er-edge"} data-edge={edge.id}>
      <path d={d} />
      {tail && <path className="er-edge-head" d={tail} />}
    </g>
  );
}

const BASE = new Set(["request", "plan"]);

/** The live process diagram: request, plan, then per part the queue, the worker, the review and the result. */
export function StatusDiagram({
  view,
  words,
  now,
  host,
}: {
  view: StatusView;
  words: RequestStatusNoun;
  now: number;
  host: RefObject<HTMLDivElement | null>;
}) {
  const baseEdges = view.edges.filter((edge) => edge.id === "e-request-plan");
  const partEdges = view.edges.filter((edge) => edge.id !== "e-request-plan");
  const baseNodes = view.nodes.filter((node) => BASE.has(node.kind));
  const partNodes = view.nodes.filter((node) => !BASE.has(node.kind));
  const baseChips = view.chips.filter((chip) => chip.node === "plan");
  const partChips = view.chips.filter((chip) => chip.node !== "plan");
  const hint = view.labels.filter((label) => label.id === "plan-hint");
  const rows = view.labels.filter((label) => label.id !== "plan-hint");
  return (
    <div className="er-diagram" ref={host} style={{ height: view.height }} data-testid="status-diagram">
      <svg className="er-edges" width="1120" height={view.height} viewBox={`0 0 1120 ${view.height}`} aria-hidden="true">
        {baseEdges.map((edge) => (
          <Edge key={edge.id} edge={edge} />
        ))}
      </svg>
      {hint.map((label) => (
        <span key={label.id} className="er-plan-hint" style={{ left: label.x, top: label.y }}>
          {label.text}
        </span>
      ))}
      {baseNodes.map((node) => (
        <Node key={node.id} node={node} words={words} />
      ))}
      {baseChips.map((chip) => (
        <Chip key={chip.id} chip={chip} now={now} />
      ))}
      {view.planned && (
        <div className="er-parts-layer" data-motion="parts">
          <svg className="er-edges" width="1120" height={view.height} viewBox={`0 0 1120 ${view.height}`} aria-hidden="true">
            {partEdges.map((edge) => (
              <Edge key={edge.id} edge={edge} />
            ))}
          </svg>
          {rows.map((label) => (
            <span key={label.id} className="er-row-label" style={{ left: label.x, top: label.y }}>
              {label.text}
            </span>
          ))}
          {partNodes.map((node) => (
            <Node key={node.id} node={node} words={words} />
          ))}
          {partChips.map((chip) => (
            <Chip key={chip.id} chip={chip} now={now} />
          ))}
        </div>
      )}
      <div className="er-dots" data-motion="dots" aria-hidden="true" />
    </div>
  );
}

function Step({ step, words, recordHref }: { step: StepView; words: RequestStatusNoun; recordHref?: string }) {
  return (
    <li className={`er-step er-step-${step.state}`} data-node={step.key} data-state={step.state} data-receipt={step.evidence ?? ""}>
      <span className="er-step-label">{step.label}</span>
      <strong className="er-step-word">
        <StateIcon state={step.state} />
        {step.word}
      </strong>
      {(step.detail || step.evidence) && (
        <span className="er-step-detail">
          {step.detail}
          {step.detail && step.evidence ? " · " : ""}
          <Evidence value={step.evidence} words={words} href={recordHref} />
        </span>
      )}
      {step.href && step.action && (
        <AppLink to={step.href} className="er-btn-primary er-step-action">
          {step.action}
        </AppLink>
      )}
    </li>
  );
}

/** The same states as stacked cards: the phone layout, and the accessible alternative to the diagram. */
export function StatusList({ view, words, recordHref }: { view: StatusView; words: RequestStatusNoun; recordHref?: string }) {
  return (
    <div className="er-status-list" data-testid="status-list">
      <article className="er-part-card">
        <ol className="er-steps-list">
          <Step step={{ key: "request", label: words.nodes.request ?? "", word: view.shortId, state: "noun", evidence: view.nodes[0]?.evidence }} words={words} recordHref={recordHref} />
          <Step step={view.planCard} words={words} recordHref={recordHref} />
        </ol>
      </article>
      {view.parts.map((part) => (
        <article key={part.part} className="er-part-card" data-part={part.part}>
          <div className="er-part-head">
            <span className="er-feature-tile er-feature-tile-small" aria-hidden="true">
              <Icon name={part.route === "private-files" ? "package" : "file-text"} size={20} />
            </span>
            <span>
              <strong>{part.title}</strong>
              <span className="er-small">{part.subtitle}</span>
            </span>
          </div>
          <ol className="er-steps-list">
            {part.steps.map((step) => (
              <Step key={step.key} step={step} words={words} recordHref={recordHref} />
            ))}
          </ol>
          {part.note && <p className="er-small">{part.note}</p>}
        </article>
      ))}
    </div>
  );
}

export function StatusLog({
  rows,
  words,
  formatTime,
  recordHref,
}: {
  recordHref?: string;
  rows: LogRow[];
  words: RequestStatusNoun;
  formatTime: (at: number) => string;
}) {
  const untimed = rows.some((row) => row.at === null);
  return (
    <section className="er-log" aria-labelledby="log-title">
      <h2 id="log-title">{words.log.title}</h2>
      {rows.length === 0 ? (
        <p className="er-small">{words.log.empty}</p>
      ) : (
        <ol className="er-log-rows">
          {rows.map((row) => (
            <li key={row.key}>
              <span className="er-log-time">{row.at === null ? "·" : formatTime(row.at)}</span>
              <span>{row.text}</span>
              <Evidence value={row.evidence} words={words} href={recordHref} />
            </li>
          ))}
        </ol>
      )}
      {untimed && <p className="er-small">{words.log.record_note}</p>}
    </section>
  );
}

export function QueuePanel({ queue, words, showAgents, note }: { queue: QueueSnapshot; words: RequestStatusNoun; showAgents: boolean; note?: string }) {
  // On an example page the queue and its agents are part of the example, never shown as the live queue (PE-02).
  const title = showAgents ? (words.queue.title_example ?? words.queue.title) : words.queue.title;
  return (
    <section className="er-panel er-queue" aria-labelledby="queue-title" data-example={showAgents}>
      <h2 id="queue-title" className="er-panel-title">
        {title}
      </h2>
      <div className="er-queue-counts">
        <span className="er-count er-count-waiting">
          <b>{queue.waiting}</b>
          {words.queue.waiting}
        </span>
        <span className="er-count er-count-verb">
          <b>{queue.working}</b>
          {words.queue.working}
        </span>
        <span className="er-count er-count-verb">
          <b>{queue.checking}</b>
          {words.queue.checking}
        </span>
      </div>
      {showAgents && (
        <p className="er-small">
          {queue.agents.length ? fill(words.queue.agents ?? "", { names: queue.agents.join(", ") }) : words.queue.no_agents}
        </p>
      )}
      <p className="er-small">{note ?? words.queue.estimates}</p>
    </section>
  );
}

export type NoticeTone = "error" | "wait" | "turn" | "info";

export function StateNotice({
  tone,
  head,
  body,
  action,
  testId,
}: {
  tone: NoticeTone;
  head: string;
  body?: string;
  action?: ReactNode;
  testId?: string;
}) {
  const icon = tone === "wait" ? "circle-dashed" : tone === "info" ? "info" : "circle-alert";
  return (
    <div className={`er-state er-state-${tone}`} data-testid={testId} role={tone === "error" ? "alert" : "status"}>
      <Icon name={icon} size={20} strokeWidth={2} />
      <div>
        <p>
          <strong>{head}</strong>
          {body ? ` ${body}` : ""}
        </p>
        {action}
      </div>
    </div>
  );
}
