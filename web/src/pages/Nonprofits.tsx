import { DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import { KitParts, PersonOnlyList, StatusNote, StepMap } from "../components/Marketplace";
import {
  AGENT_KIT_DEFINITION,
  PACK_LIBRARY_URL,
  REQUEST_KIT_URL,
  WHOLE_SETUP,
} from "../lib/marketplace";
import type { CatalogResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

const EXPLOITATION_PACK_URL = `${PACK_LIBRARY_URL}/tree/main/packs/exploitation-evidence`;

/** The nonprofit side of the marketplace: NGOs and public-good groups looking for agentic solutions. */
export function Nonprofits() {
  const catalog = useResource<CatalogResponse>("/api/catalog");

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
          <a className="er-btn-secondary" href="#request">
            Request a kit
          </a>
        </div>
      </section>

      <section className="er-section" aria-labelledby="parts-title">
        <h2 id="parts-title">What is in an agent kit</h2>
        <KitParts />
        <p className="er-muted er-measure">{WHOLE_SETUP}</p>
        <p className="er-muted er-measure er-mt-10">
          The five examples below hold instructions, skills, knowledge, connections, a step map, and checks and
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
        <h2 id="request-title">Request a kit</h2>
        <p className="er-warning" role="note">
          <strong>Don&apos;t include anyone&apos;s personal information. Requests are public.</strong>
        </p>
        <p className="er-muted er-measure er-mb-12">
          Tell volunteers about a job your organization needs done. The form asks for your type of
          organization, the job, the steps that must stay with a person, and any limits, such as languages or
          rules you follow.
        </p>
        <ol className="er-plain-steps">
          <li>Open the request form on GitHub. You need a free GitHub account.</li>
          <li>
            A volunteer will check your request before it becomes work. The check looks at fit with a track,
            the safety rules and the synthetic-data rule.
          </li>
          <li>
            If it passes, it becomes a task brief. One volunteer&apos;s agent builds the kit, and a different
            volunteer reviews it.
          </li>
        </ol>
        <p className="er-muted er-measure er-mt-12">
          Kits are reviewed, not certified. Check any kit with your own staff and rules before you use it.
          Volunteers pick up requests when they can, so there is no set timeline.
        </p>
        <div className="er-actions er-mt-12">
          <a className="er-btn-primary" href={REQUEST_KIT_URL}>
            Request a kit
          </a>
        </div>
        <p className="er-small er-mt-10">Opens a public form on GitHub. This site does not store requests.</p>
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
