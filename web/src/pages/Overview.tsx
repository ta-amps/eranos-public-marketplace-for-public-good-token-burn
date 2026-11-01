import { SNAPSHOT } from "../config";
import { countWords, fill, type HomeNoun, type SiteNoun } from "../lib/nouns";
import type { CatalogResponse, FabricResponse } from "../lib/types";
import { useNoun } from "../lib/useNoun";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";
import { Icon } from "../components/Icon";

/** Tiles of the mark at three depths behind the landing. They move only while the page scrolls. */
const LAYERS = [
  { id: "a", depth: "far" },
  { id: "b", depth: "far" },
  { id: "c", depth: "mid" },
  { id: "d", depth: "mid" },
  { id: "e", depth: "near" },
  { id: "f", depth: "near" },
] as const;

function clock(at: number): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(at));
}

/** Live counts from the queue. Absent, not zeros, when the queue can't be reached or this copy is offline. */
function RightNow({ home }: { home: HomeNoun }) {
  const fabric = useResource<FabricResponse>("/api/fabric");
  const catalog = useResource<CatalogResponse>("/api/catalog?view=page");
  if (SNAPSHOT || fabric.state.status !== "ready" || fabric.state.data.queues.length === 0) return null;
  const queues = new Map(fabric.state.data.queues.map((q) => [q.name, q]));
  const intake = queues.get("eq01");
  const requests = (intake?.ready ?? 0) + (intake?.leased ?? 0) + (intake?.waiting ?? 0);
  const open = ["eq01", "eq02", "eq03"].reduce((sum, name) => sum + (queues.get(name)?.ready ?? 0), 0);
  const working = ["eq01", "eq02", "eq03"].reduce((sum, name) => sum + (queues.get(name)?.leased ?? 0), 0);
  const kits = catalog.state.status === "ready" ? catalog.state.data.kits.length : null;
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
      </ul>
      <p className="er-small">{fill(home.now.note, { time: clock(Date.now()) })}</p>
    </section>
  );
}

/** The home page: a quiet landing with exactly two buttons, then what you can ask for, how it works and answers. */
export function Overview({ site }: { site: SiteNoun | null }) {
  const home = useNoun<HomeNoun>("home").value;

  return (
    <div className="er-home">
      <section className="er-landing" aria-labelledby="hero-title" data-testid="landing">
        <div className="er-landing-layers" aria-hidden="true">
          {LAYERS.map((layer) => (
            <span key={layer.id} className={`er-layer er-layer-${layer.id} er-depth-${layer.depth}`} />
          ))}
        </div>
        <div className="er-landing-inner er-landing-center">
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
        {home?.track && (
          // The request track in miniature, at the foot of the hero. The real one is each request's own page.
          <ol className="er-landing-track" aria-hidden="true">
            {home.track.map((station, index) => (
              <li key={station} className={`er-landing-station er-landing-station-${index}`}>
                {station}
              </li>
            ))}
          </ol>
        )}
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
