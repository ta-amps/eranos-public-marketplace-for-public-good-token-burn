import { DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import { KitParts, PersonOnlyList, StatusNote, StepMap } from "../components/Marketplace";
import { RequestBox } from "../components/RequestBox";
import {
  AGENT_KIT_DEFINITION,
  PACK_LIBRARY_URL,
  REQUEST_KIT_URL,
  WHOLE_SETUP,
} from "../lib/marketplace";
import type { CatalogResponse, ExampleNeed, ExamplesResponse } from "../lib/types";
import type { NonprofitsNoun, NounResponse } from "../lib/nouns";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

const EXPLOITATION_PACK_URL = `${PACK_LIBRARY_URL}/tree/main/packs/exploitation-evidence`;

/** The nonprofit side of the marketplace: NGOs and public-good groups looking for agentic solutions. */
export function Nonprofits() {
  const catalog = useResource<CatalogResponse>("/api/catalog");
  const examples = useResource<ExamplesResponse>("/api/examples");
  const needs = new Map<string, ExampleNeed>(
    examples.state.status === "ready" ? examples.state.data.needs.map((need) => [need.kit_id, need]) : [],
  );
  const guide = useResource<NounResponse<NonprofitsNoun>>("/api/nouns/eranos.instructions/nonprofits");
  const noun = guide.state.status === "ready" ? guide.state.data.value : null;

  return (
    <div>
      <section className="er-hero" aria-labelledby="ngo-title">
        <span className="er-chip er-chip-drafts er-mb-12">For nonprofits, NGOs and public-good groups</span>
        <h1 id="ngo-title">Agent kits for nonprofits, NGOs and public-good groups</h1>
        <p className="er-lede">
          {AGENT_KIT_DEFINITION} Volunteers build kits with AI capacity they donate, and a different volunteer
          reviews each one before it is shared.
        </p>
        <div className="er-hero-links">
          <a className="er-btn-primary" href="#examples">
            Browse example kits
          </a>
          {noun && (
            <a className="er-btn-secondary" href="#request">
              {noun.form.label}
            </a>
          )}
        </div>
      </section>

      <section className="er-section" aria-labelledby="parts-title">
        <h2 id="parts-title">What is in an agent kit</h2>
        <KitParts />
        <p className="er-muted er-measure">{WHOLE_SETUP}</p>
        <p className="er-muted er-measure er-mt-10">
          The examples below hold instructions, skills, knowledge, connections, a step map, and checks and
          tests. None of them includes agent settings yet.
        </p>
      </section>

      <section className="er-section" id="examples" aria-labelledby="examples-title" data-testid="example-kits">
        <h2 id="examples-title">Browse reviewed example kits</h2>
        <p className="er-muted er-measure er-mb-12">
          Each kit passed its checks and tests, then a review by a different volunteer. All of them use
          synthetic data. Kits on the anti-exploitation tracks use warning-sign patterns from the{" "}
          <a href={EXPLOITATION_PACK_URL}>exploitation-evidence pack</a> in our{" "}
          <a href={PACK_LIBRARY_URL}>pack library</a>.
        </p>
        {catalog.state.status === "loading" && <p className="er-muted">Loading example kits...</p>}
        {catalog.state.status === "error" && (
          <ErrorAlert title="Example kits unavailable" message={catalog.state.message} onRetry={catalog.reload} />
        )}
        {catalog.state.status === "ready" && (
          <div className="er-grid er-grid-kits">
            {catalog.state.data.kits.map((entry) => {
              const license = entry.spdx_license || entry.kit.spdx_license || "Apache-2.0";
              const need = needs.get(entry.kit.kit_id);
              return (
                <article key={entry.kit.kit_id} className="er-card" data-testid="example-kit">
                  <div className="er-chip-row">
                    <DomainBadge domain={entry.kit.domain} />
                    <span className="er-chip er-chip-neutral">Open license: {license}</span>
                    {entry.steward_signoff && <span className="er-chip er-chip-steward">Steward signed off</span>}
                  </div>
                  <h3>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h3>
                  <p className="er-muted">
                    <strong>For:</strong> {entry.kit.target_org}
                  </p>
                  <p className="er-muted">{entry.kit.summary}</p>
                  {need && (
                    <figure className="er-need" data-testid="example-need">
                      <figcaption>
                        {need.title} <span className="er-chip er-chip-neutral">{need.mark}</span>
                      </figcaption>
                      <blockquote>{need.says}</blockquote>
                    </figure>
                  )}
                  <h4 className="er-card-subhead">Step map</h4>
                  <StepMap steps={entry.kit.steps} />
                  <p className="er-small">
                    Built by <code>{entry.kit.drafted_by}</code>, reviewed by <code>{entry.reviewed_by}</code>.
                  </p>
                  <div className="er-actions er-mt-auto">
                    <AppLink to={`/catalog/${entry.kit.kit_id}`} className="er-btn-secondary">
                      Open the kit
                    </AppLink>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        <div className="er-actions">
          <AppLink to="/catalog" className="er-btn-secondary">
            Open the full catalog
          </AppLink>
        </div>
      </section>

      <section className="er-section er-request" id="request" aria-labelledby="request-title" data-testid="request-kit">
        {guide.state.status === "error" && (
          <ErrorAlert title="The request form is unavailable" message={guide.state.message} onRetry={guide.reload} />
        )}
        {noun && (
          <>
            <h2 id="request-title">{noun.title}</h2>
            <p className="er-warning" role="note">
              <strong>{noun.warning}</strong>
            </p>
            <RequestBox noun={noun} />
            <ol className="er-plain-steps er-mt-12" data-testid="request-steps">
              {noun.steps.map((step) => (
                <li key={step.id}>
                  <strong>{step.title}.</strong> {step.detail}
                </li>
              ))}
            </ol>
            <p className="er-muted er-measure er-mt-12">{noun.follow}</p>
            <p className="er-small er-mt-10">
              <a href={REQUEST_KIT_URL}>{noun.form_on_github}</a>
            </p>
          </>
        )}
      </section>

      <section className="er-section" aria-labelledby="people-title">
        <h2 id="people-title">What stays with your people</h2>
        <p className="er-muted er-measure er-mb-12">
          An agent prepares and checks. Your staff decide. These always stay with a person:
        </p>
        <PersonOnlyList />
      </section>

      <StatusNote />
    </div>
  );
}
