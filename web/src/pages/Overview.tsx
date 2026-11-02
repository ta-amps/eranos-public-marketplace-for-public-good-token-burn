import { LIVE_QUEUE_POLL_MS, SNAPSHOT } from "../config";
import { countWords, fill, type HomeNoun, type SiteNoun } from "../lib/nouns";
import type { CatalogResponse, FabricResponse } from "../lib/types";
import { useNoun } from "../lib/useNoun";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";
import { Icon } from "../components/Icon";
import { RightNowStrip } from "../components/RightNowStrip";

/** The process tiles' icons (EranosHome board, Lucide paths): a request, picked up, checked, public good. */
const TILE_ICONS = [
  "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4",
  "M12 8V5M9 5h6M6 8h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM9.5 13v1.5M14.5 13v1.5",
  "M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3",
  "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
] as const;

const PIPELINE_QUEUES = ["eq01", "eq02", "eq03"] as const;

function clock(at: number): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(at));
}

/** Live counts from the queue. Absent, not zeros, when the queue can't be reached or this copy is offline. */
function RightNow({ home }: { home: HomeNoun }) {
  const fabric = useResource<FabricResponse>("/api/fabric", { pollMs: LIVE_QUEUE_POLL_MS });
  const catalog = useResource<CatalogResponse>("/api/catalog?view=page");
  if (SNAPSHOT || fabric.state.status !== "ready" || fabric.state.data.queues.length === 0) return null;
  const queues = new Map(fabric.state.data.queues.map((q) => [q.name, q]));
  const requests = PIPELINE_QUEUES.reduce((sum, name) => {
    const q = queues.get(name);
    return sum + (q?.ready ?? 0) + (q?.leased ?? 0) + (q?.waiting ?? 0);
  }, 0);
  const open = PIPELINE_QUEUES.reduce((sum, name) => sum + (queues.get(name)?.ready ?? 0), 0);
  const working = PIPELINE_QUEUES.reduce((sum, name) => sum + (queues.get(name)?.leased ?? 0), 0);
  const kits = catalog.state.status === "ready" ? catalog.state.data.kits.length : null;
  const swarm = fabric.state.data.swarm;
  return (
    <section className="er-container er-now" aria-labelledby="now-title" data-testid="right-now">
      <h2 id="now-title" className="er-now-title">
        {home.now.title}
      </h2>
      <ul>
        <li>{countWords(home.now.requests, requests)}</li>
        <li>{countWords(home.now.open, open)}</li>
        <li>{countWords(home.now.working, working)}</li>
        {kits !== null && <li>{countWords(home.now.kits, kits)}</li>}
        {swarm && home.now.swarm && (
          <li data-testid="right-now-swarm">
            {fill(home.now.swarm, {
              open: swarm.ngo_ready + swarm.general_ready,
              ngo_ready: swarm.ngo_ready,
              leased: swarm.ngo_leased + swarm.general_leased,
              workers: swarm.registered_workers,
              done: swarm.ngo_done + swarm.general_done,
            })}
          </li>
        )}
      </ul>
      <p className="er-small">{fill(home.now.note, { time: clock(fabric.updatedAt) })}</p>
    </section>
  );
}

/** The home page: a quiet landing with exactly two buttons, then what you can ask for, how it works and answers. */
export function Overview({ site }: { site: SiteNoun | null }) {
  const home = useNoun<HomeNoun>("home").value;

  return (
    <div className="er-home">
      <section className="er-landing" aria-labelledby="hero-title" data-testid="landing">
        {/* The split hero (EranosHome, Nov 2): words and the two doors on the left, the four process tiles on the
            right. The tiles sit in their own column, so nothing in them ever crosses the hero's text; they only light
            up once after load (opacity), and never move. */}
        <div className="er-landing-inner er-landing-split">
          <div className="er-landing-words">
            {home && <p className="er-landing-pill">{home.eyebrow}</p>}
            <h1 id="hero-title" className="er-display">
              {site?.headline ?? ""}
            </h1>
            {(home?.lead ?? site?.subline) && <p className="er-landing-lead">{home?.lead ?? site?.subline}</p>}
            {home && (
              <div className="er-landing-buttons" role="group" aria-label={home.buttons_label}>
                {/* The two doors (EranosHome): "My NGO needs help" first and left, in ink; "I want to help" outlined. */}
                {home.buttons.map((button, index) => (
                  <AppLink
                    key={button.id}
                    to={button.to}
                    className={index === 0 ? "er-btn-primary er-door er-door-ink" : "er-btn-secondary er-door er-door-paper"}
                    data-door={button.id}
                  >
                    <span className="er-door-label">
                      {button.label}
                      <Icon name="arrow-right" size={24} />
                    </span>
                    {button.sub && (
                      <span className="er-door-sub">
                        <span className="er-long">{button.sub}</span>
                        <span className="er-short">{button.sub_short ?? button.sub}</span>
                      </span>
                    )}
                  </AppLink>
                ))}
              </div>
            )}
            {home && (
              <p className="er-honesty">
                <span className="er-long">{home.honesty}</span>
                <span className="er-short">{home.honesty_short ?? home.honesty}</span>
              </p>
            )}
          </div>
          {home?.process && (
            <ol className="er-hero-tiles" aria-label={home.process.label}>
              {home.process.steps.map((step, index) => (
                <li key={step.title} className={`er-hero-tile er-hero-tile-${index}`}>
                  <span className="er-hero-tile-lit" aria-hidden="true" />
                  <span className="er-hero-tile-body">
                    <span className="er-hero-tile-head">
                      <span className="er-hero-tile-n" aria-hidden="true">
                        {index + 1}
                      </span>
                      <svg className="er-hero-tile-icon" aria-hidden="true" width="30" height="30" viewBox="0 0 24 24" fill="none" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                        <path d={TILE_ICONS[index] ?? TILE_ICONS[0]} />
                      </svg>
                    </span>
                    <strong className="er-hero-tile-title">{step.title}</strong>
                    <span className="er-hero-tile-text">
                      <span className="er-long">{step.text}</span>
                      <span className="er-short">{step.text_short ?? step.text}</span>
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          )}
          {home?.right_now && <RightNowStrip words={home.right_now} />}
        </div>
      </section>

      {home && (
        <>
          <section className="er-asks" aria-labelledby="gets-title">
            <div className="er-container">
              <h2 id="gets-title">{home.gets.title}</h2>
              <div className="er-asks-grid">
                {home.gets.items.map((item) => (
                  <article key={item.id} className="er-ask-card" data-kind={item.id}>
                    {item.tag && <span className={item.id === "process" ? "er-kind-tag er-kind-tag-task" : "er-kind-tag er-kind-tag-object"}>{item.tag}</span>}
                    <h3>{item.title}</h3>
                    <p>{item.line}</p>
                    {item.examples && (
                      <ul className="er-ask-examples">
                        {item.examples.map((example) => (
                          <li key={example}>
                            <Icon name="arrow-right" size={16} />
                            {example}
                          </li>
                        ))}
                      </ul>
                    )}
                    {item.link && item.to && (
                      <AppLink to={item.to} className="er-text-link">
                        {item.link} →
                      </AppLink>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="er-container er-how" aria-labelledby="how-title">
            <div className="er-how-head">
              <h2 id="how-title">{home.how.title}</h2>
              <AppLink to={home.how.to} className="er-text-link">
                {home.how.link} →
              </AppLink>
            </div>
            <ol className="er-how-steps">
              {home.how.steps.map((step, index) => (
                <li key={step.title}>
                  <span className="er-step-number">{index + 1}</span>
                  <strong>{step.title}</strong>
                  <span>{step.detail}</span>
                </li>
              ))}
            </ol>
          </section>

          <RightNow home={home} />

          <section className="er-safety" aria-labelledby="safety-title">
            <div className="er-container">
              <h2 id="safety-title" className="er-visually-hidden">
                {home.safety.title}
              </h2>
              <dl className="er-safety-grid">
                {home.safety.items.map((item) => (
                  <div key={item.q}>
                    <dt>{item.q}</dt>
                    <dd>{item.a}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
