import { ErrorAlert } from "../components/ErrorAlert";
import { Icon } from "../components/Icon";
import { RequestBox, type LibraryWords } from "../components/RequestBox";
import type { NonprofitsPageNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

/**
 * "My NGO needs help": the request page sets the bounds first (no private information at this stage), then asks
 * what kind of output, how often and what the job is, in one box. The side column says what happens after Send
 * and the two kinds of results, each with a labelled example. Every word is the `nonprofits-page` noun.
 */
export function Nonprofits() {
  const { value: page, failed, reload } = useNoun<NonprofitsPageNoun>("nonprofits-page");
  const libraryWords = useNoun<LibraryWords>("library").value;
  if (failed && !page) return <ErrorAlert title="This page is unavailable" message="Its text could not load." onRetry={reload} />;
  if (!page) return null;
  const adapting = new URLSearchParams(window.location.search).has("improve");
  return (
    <div className="er-ask-page">
      <section className="er-ask-main" aria-labelledby="ngo-title" data-testid="request-kit">
        <p className="er-eyebrow">{page.eyebrow}</p>
        <h1 id="ngo-title">{adapting ? page.form.adapt.heading : page.heading}</h1>
        <p className="er-lede">{adapting ? page.form.adapt.lead : page.lead}</p>
        <p className="er-bounds" role="note" data-testid="request-bounds">
          <Icon name="lock-keyhole" size={20} />
          <span>
            <strong>{page.bounds.head}</strong> {page.bounds.body}
          </span>
        </p>
        <RequestBox page={page} libraryWords={libraryWords} />
      </section>
      <aside className="er-ask-aside" aria-label={page.aside.next_title}>
        <section className="er-panel">
          <h2>{page.aside.next_title}</h2>
          <ol className="er-next-steps">
            {page.aside.steps.map((step, index) => (
              <li key={step.title}>
                <span className="er-step-dot" aria-hidden="true">
                  {index + 1}
                </span>
                <span>
                  <strong>{step.title}</strong> {step.detail}
                </span>
              </li>
            ))}
          </ol>
          <AppLink to={page.aside.example_to} className="er-text-link">
            {page.aside.example_link} →
          </AppLink>
        </section>
        <section className="er-panel">
          <h2 className="er-panel-title">{page.aside.kinds_title}</h2>
          <ul className="er-kinds">
            {page.aside.kinds.map((kind) => (
              <li key={kind.name}>
                <strong>{kind.name}</strong>: {kind.line} <AppLink to={kind.to}>{kind.link}</AppLink>
              </li>
            ))}
          </ul>
          <AppLink to={page.aside.kits_to}>{page.aside.kits_link}</AppLink>
        </section>
      </aside>
    </div>
  );
}
