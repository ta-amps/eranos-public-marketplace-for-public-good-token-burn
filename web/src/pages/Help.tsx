import { useMemo, useRef, useState } from "react";

import { publicNames } from "../lib/publicNames";
import { Icon } from "../components/Icon";
import { LIVE_QUEUE_POLL_MS, SNAPSHOT } from "../config";
import { briefWithInterests, fill, type HelpNoun, type HelpPageNoun } from "../lib/nouns";
import type { RequestExampleNoun } from "../lib/status/example";
import { shortReceipt } from "../lib/status/ids";
import type { FabricResponse, SharedTasksResponse } from "../lib/types";
import { useNoun } from "../lib/useNoun";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

type Mode = "any" | "interests";

interface OpenTask {
  task_id: string;
  queue: string;
  kind: string;
  title: string;
  created_at: number | null;
  open_to_anonymous: boolean;
}

function waited(words: HelpPageNoun["tasks"], createdAt: number | null): string {
  if (!createdAt) return "";
  const minutes = Math.max(1, Math.round((Date.now() / 1000 - createdAt) / 60));
  const amount = minutes < 120 ? fill(words.minutes, { n: minutes }) : minutes < 2880 ? fill(words.hours, { n: Math.round(minutes / 60) }) : fill(words.days, { n: Math.round(minutes / 1440) });
  return fill(words.waiting, { ago: amount });
}

/** "I want to help": the instructions to copy first, then the open work, then what your tokens did. */
export function Help() {
  const page = useNoun<HelpPageNoun>("help-page").value;
  const help = useNoun<HelpNoun>("help").value;
  const example = useNoun<RequestExampleNoun>("request-example").value;
  const fabric = useResource<FabricResponse>("/api/fabric", { pollMs: LIVE_QUEUE_POLL_MS });
  const open = useResource<{ tasks: OpenTask[] }>("/api/open-tasks", { pollMs: LIVE_QUEUE_POLL_MS });
  const shared = useResource<SharedTasksResponse>("/api/shared-tasks", { pollMs: 60_000 });
  const [copiedTask, setCopiedTask] = useState("");
  const [mode, setMode] = useState<Mode>("any");
  const [interests, setInterests] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState("");
  const brief = useRef<HTMLPreElement>(null);
  const interestsBox = useRef<HTMLInputElement>(null);

  const text = useMemo(() => {
    if (!help) return "";
    return mode === "interests" && interests.trim() ? briefWithInterests(help, interests) : help.brief;
  }, [help, mode, interests]);

  if (!page) return null;
  const connect = page.connect;
  const tasks = page.tasks;
  const chips = interests
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  async function copy() {
    if (!help) return;
    if (mode === "interests" && !interests.trim()) {
      setStatus(connect.add_first ?? "");
      interestsBox.current?.focus();
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus(connect.copied ?? "");
    } catch {
      setExpanded(true);
      setStatus(connect.copy_failed ?? "");
      const range = document.createRange();
      if (brief.current) {
        range.selectNodeContents(brief.current);
        window.getSelection()?.removeAllRanges();
        window.getSelection()?.addRange(range);
      }
    }
  }

  const queues = fabric.state.status === "ready" ? fabric.state.data.queues : [];
  const swarm = fabric.state.status === "ready" ? fabric.state.data.swarm : undefined;
  const fabricLive = !SNAPSHOT && fabric.state.status === "ready" && queues.length > 0;
  const total = queues.reduce((sum, q) => sum + (q.ready ?? 0), 0);
  const submitted = example?.events.find((e) => e.type === "work_submitted");
  const approved = example?.events.find((e) => e.type === "check_approved");

  return (
    <div className="er-help-page">
      <section className="er-help-hero" aria-labelledby="help-title">
        <p className="er-eyebrow">{page.eyebrow}</p>
        <h1 id="help-title">{page.heading}</h1>
        <p className="er-lede">{page.lead}</p>
      </section>
      <div className="er-help-columns">
        <div className="er-help-main">
          <section className="er-panel er-panel-large" aria-labelledby="connect-title" data-testid="agent-brief">
            <h2 id="connect-title">
              <span className="er-section-number">1</span>
              {connect.title}
            </h2>
            <div className="er-modes" role="radiogroup" aria-label={connect.modes_label}>
              {(["any", "interests"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={mode === value}
                  className="er-mode"
                  onClick={() => {
                    setMode(value);
                    setStatus("");
                  }}
                >
                  {value === "any" ? connect.mode_any : connect.mode_interests}
                </button>
              ))}
            </div>
            {mode === "interests" && (
              <div className="er-field er-interests">
                <label htmlFor="interests">{connect.interests_label}</label>
                <input
                  id="interests"
                  ref={interestsBox}
                  className="er-input"
                  maxLength={1500}
                  value={interests}
                  placeholder={connect.interests_placeholder}
                  aria-describedby="interests-hint"
                  onChange={(event) => setInterests(event.target.value)}
                />
                <p id="interests-hint" className="er-small">
                  {connect.interests_hint}
                </p>
                {chips.length > 0 && (
                  <p className="er-chip-row">
                    <span className="er-small">{connect.interests_chips}</span>
                    {chips.map((chip) => (
                      <span key={chip} className="er-chip er-chip-neutral">
                        {chip}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            )}
            <pre
              ref={brief}
              className={expanded ? "er-brief-text er-brief-open" : "er-brief-text"}
              aria-label={connect.brief_label}
              data-testid="brief-text"
              tabIndex={0}
            >
              {text}
            </pre>
            <button type="button" className="er-btn-quiet er-brief-toggle" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
              {expanded ? connect.show_less : connect.show_all}
            </button>
            <div className="er-actions">
              <button type="button" className="er-btn-primary er-btn-large" onClick={() => void copy()} disabled={!help}>
                <Icon name="copy" size={18} />
                {connect.copy}
              </button>
              <a href={connect.key_href} className="er-text-link">
                {connect.key_link}
              </a>
            </div>
            <p className="er-brief-status" role="status" aria-live="polite">
              {status}
            </p>
            <p className="er-small">{connect.works_with}</p>
            <p className="er-small">{connect.demo_note}</p>
            <AppLink to={connect.other_ways_to ?? "/contribute"}>{connect.other_ways}</AppLink>
          </section>

          <section className="er-panel er-panel-large" aria-labelledby="tasks-title" data-testid="open-work">
            <div className="er-panel-head">
              <h2 id="tasks-title">
                <span className="er-section-number">2</span>
                {tasks.title}
              </h2>
              {fabricLive && <span className="er-small">{tasks.live}</span>}
            </div>
            <p className="er-small" data-testid="first-pick">
              {tasks.first_pick}
            </p>
            {!SNAPSHOT && open.state.status === "ready" && open.state.data.tasks.length > 0 ? (
              <ul className="er-open-tasks" data-testid="open-task-list">
                {open.state.data.tasks.map((task) => (
                  <li key={task.task_id}>
                    <span className="er-open-task-title">
                      <strong>{publicNames(task.title || task.task_id)}</strong>
                    </span>
                    <span className={task.queue === "eq03" ? "er-chip er-chip-task" : "er-chip er-chip-object"}>{tasks.by_kind[task.kind] ?? task.kind}</span>
                    <span className="er-small">
                      {waited(tasks, task.created_at)}
                      {!task.open_to_anonymous ? ` · ${tasks.check_needs_key}` : ""}
                    </span>
                    <button
                      type="button"
                      className="er-btn-secondary er-btn-small"
                      onClick={() =>
                        void navigator.clipboard.writeText(fill(tasks.claim_text, { task: task.task_id, queue: task.queue })).then(
                          () => setCopiedTask(task.task_id),
                          () => setCopiedTask(""),
                        )
                      }
                    >
                      {copiedTask === task.task_id ? tasks.copied : tasks.copy_for_agent}
                    </button>
                  </li>
                ))}
              </ul>
            ) : fabric.state.status === "error" || (fabric.state.status === "ready" && !fabricLive) ? (
              <p className="er-small">{tasks.unavailable}</p>
            ) : fabricLive && total === 0 ? (
              <div className="er-state er-state-wait" data-testid="no-open-tasks">
                <Icon name="circle-dashed" size={20} strokeWidth={2} />
                <p>
                  <strong>{tasks.empty_head}</strong> {tasks.empty_body}
                </p>
              </div>
            ) : (
              fabricLive && (
                <ul className="er-task-counts">
                  {queues.map((q) => (
                    <li key={q.name}>
                      <span>{tasks.kinds[q.name] ?? q.name}</span>
                      <strong>{q.ready === 1 ? tasks.count_one : fill(tasks.count_many, { n: q.ready })}</strong>
                    </li>
                  ))}
                </ul>
              )
            )}
            {fabricLive && swarm && tasks.swarm_head && tasks.swarm_body && (
              <p className="er-small" data-testid="shared-swarm-summary">
                <strong>{tasks.swarm_head}</strong>{" "}
                {fill(tasks.swarm_body, {
                  open: swarm.ngo_ready + swarm.general_ready,
                  ngo_ready: swarm.ngo_ready,
                  leased: swarm.ngo_leased + swarm.general_leased,
                  workers: swarm.registered_workers,
                  done: swarm.ngo_done + swarm.general_done,
                  objects: swarm.stored_task_objects,
                })}
              </p>
            )}
            {!SNAPSHOT && tasks.shared_title && shared.state.status === "ready" && shared.state.data.available && (
              <div className="er-shared-tasks" data-testid="shared-task-list">
                <h3>{tasks.shared_title}</h3>
                {shared.state.data.tasks.length > 0 ? (
                  <>
                    <p className="er-small">{fill(tasks.shared_count ?? "", { n: shared.state.data.total ?? shared.state.data.tasks.length })}</p>
                    <ul className="er-open-tasks">
                      {shared.state.data.tasks.map((task, index) => (
                        <li key={`${index}-${task.title}`}>
                          <span className="er-open-task-title">
                            <strong>{publicNames(task.title)}</strong>
                          </span>
                          <span className={task.tier === "ngo_priority" ? "er-chip er-chip-task" : "er-chip er-chip-object"}>
                            {tasks.shared_tier?.[task.tier] ?? task.tier}
                          </span>
                          <span className="er-small">{waited(tasks, task.created_at ? Date.parse(task.created_at) / 1000 : null)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="er-small">{tasks.shared_none}</p>
                )}
                {tasks.shared_link && tasks.shared_href && <a href={tasks.shared_href}>{tasks.shared_link}</a>}
              </div>
            )}
            <p className="er-small">{tasks.guard_note}</p>
            <p className="er-small">{tasks.list_note}</p>
            {page.map_notice && (
              <p className="er-small" data-testid="map-notice">
                {page.map_notice}
              </p>
            )}
          </section>

          <section className="er-panel er-panel-large" aria-labelledby="tokens-title" data-testid="your-tokens">
            <h2 id="tokens-title">
              <span className="er-section-number">3</span>
              {page.tokens.title}
            </h2>
            <p data-testid="tokens-empty">{page.tokens.empty}</p>
            <p className="er-small">
              {page.tokens.key_note} <a href={connect.key_href}>{connect.key_link}</a>
            </p>
            {submitted?.receipt && approved?.receipt && (
              <figure className="er-ledger">
                <figcaption>
                  <strong>{page.tokens.example_title}</strong>
                  <span className="er-small">{page.tokens.example_caption}</span>
                </figcaption>
                <ul>
                  {page.tokens.rows.map((row) => (
                    <li key={row.head} className={`er-ledger-row er-ledger-${row.tone}`}>
                      <Icon name={row.tone === "real" ? "circle-check" : "circle-x"} size={20} strokeWidth={2} />
                      <span>
                        <strong>{row.head}</strong> {fill(row.body, { checker: approved.worker ?? "" })}{" "}
                        <span className="er-receipt">
                          {fill(row.receipts, { r1: shortReceipt(submitted.receipt ?? ""), r2: shortReceipt(approved.receipt ?? "") })}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </figure>
            )}
          </section>
        </div>

        <aside className="er-help-aside">
          <section className="er-panel" aria-labelledby="agent-title" data-testid="your-agent">
            <h2 id="agent-title" className="er-panel-title">
              {page.agent.title}
            </h2>
            <p className="er-small">{page.agent.none}</p>
          </section>
          <section className="er-panel er-panel-dark" aria-labelledby="rules-title">
            <h2 id="rules-title" className="er-panel-title">
              {page.rules.title}
            </h2>
            <ul>
              {page.rules.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
      <p className="er-small er-mt-12">
        {page.safety} <AppLink to="/about">{page.safety_link}</AppLink>
      </p>
    </div>
  );
}
