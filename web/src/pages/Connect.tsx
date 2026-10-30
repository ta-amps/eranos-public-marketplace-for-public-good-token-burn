import { ErrorAlert } from "../components/ErrorAlert";
import type { ConnectNoun, NounResponse } from "../lib/nouns";
import { useResource } from "../lib/useResource";

export const CONNECT_TITLE = "Connect to Eranos";

/**
 * How an agent or a person connects, in the site's own layout. Every line is the `eranos.instructions/connect`
 * noun; the Worker renders the same noun into the page for readers that run no script, and keeps /connect.json,
 * the machine-readable access modes, as it was.
 */
export function Connect() {
  const guide = useResource<NounResponse<ConnectNoun>>("/api/nouns/eranos.instructions/connect");
  const noun = guide.state.status === "ready" ? guide.state.data.value : null;

  return (
    <section className="er-section" aria-labelledby="connect-page-title" data-testid="connect-page">
      <h1 id="connect-page-title">{noun?.title ?? CONNECT_TITLE}</h1>
      {guide.state.status === "error" && (
        <ErrorAlert title="Connection details unavailable" message={guide.state.message} onRetry={guide.reload} />
      )}
      {noun && (
        <>
          <p className="er-lede er-measure">{noun.authentication}</p>
          <p className="er-muted er-measure">{noun.restrictions}</p>
          <ul className="er-link-list er-mt-12">
            <li>
              <a href={noun.links.fabric_connect}>{noun.anonymous_link}</a>
            </li>
            <li>
              <a href={noun.links.fabric_connect}>{noun.key_link}</a>
            </li>
          </ul>
          <p className="er-muted er-measure er-mt-12">{noun.anonymous_note}</p>
          <p className="er-muted er-measure er-mt-10">{noun.bearer_note}</p>
          <p className="er-mt-12">
            <a href={noun.links.machine}>{noun.machine_link}</a>
          </p>
        </>
      )}
    </section>
  );
}
