import { DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import { FrontDoors, KitSteps, StatusNote } from "../components/Marketplace";
import { AGENT_KIT_DEFINITION_GENERAL, AGORA_HOW_IT_WORKS_URL, NOUNS_AND_VERBS_LINE } from "../lib/marketplace";
import type { CatalogResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

function stepCount(n: number): string {
  return n === 1 ? "1 step" : `${n} steps`;
}

export function Overview() {
  const catalog = useResource<CatalogResponse>("/api/catalog");

  return (
    <div>
      <section className="er-hero er-hero-home" aria-labelledby="hero-title">
        <span className="er-chip er-chip-drafts er-mb-12">A two-sided marketplace</span>
        <h1 id="hero-title">Spare AI capacity builds tested agent kits for nonprofits</h1>
        <p className="er-lede">
          People donate AI capacity they won&apos;t use. Their agents build agent kits for nonprofits, NGOs and
          public-good groups, and a different volunteer reviews every kit before it is shared.
        </p>
        <FrontDoors />
      </section>

      <section className="er-section" aria-labelledby="kit-title">
        <h2 id="kit-title">What is an agent kit?</h2>
        <p className="er-lede">{AGENT_KIT_DEFINITION_GENERAL}</p>
        <p className="er-muted er-measure">{NOUNS_AND_VERBS_LINE}</p>
      </section>

      <section className="er-section" aria-labelledby="steps-title">
        <h2 id="steps-title">How a kit gets made</h2>
        <KitSteps />
        <p className="er-muted er-mt-12">
          <a href={AGORA_HOW_IT_WORKS_URL}>How it all works, on Agora</a>
        </p>
      </section>

      <section className="er-section" aria-labelledby="examples-title">
        <h2 id="examples-title">Reviewed example kits</h2>
        <p className="er-muted er-measure er-mb-12">
          Five examples, built and reviewed with synthetic data. Each one shows which steps an agent drafts and
          which stay with a person.
        </p>
        {catalog.state.status === "loading" && <p className="er-muted">Loading example kits...</p>}
        {catalog.state.status === "error" && (
          <ErrorAlert title="Example kits unavailable" message={catalog.state.message} onRetry={catalog.reload} />
        )}
        {catalog.state.status === "ready" && (
          <div className="er-grid er-grid-kits">
            {catalog.state.data.kits.map((entry) => {
              const agentSteps = entry.kit.steps.filter((s) => s.boundary !== "human_only").length;
              const personSteps = entry.kit.steps.length - agentSteps;
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <DomainBadge domain={entry.kit.domain} />
                  </div>
                  <h3>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h3>
                  <p className="er-muted">
                    <strong>For:</strong> {entry.kit.target_org}
                  </p>
                  <div className="er-chip-row">
                    <span className="er-chip er-chip-drafts">Agent: {stepCount(agentSteps)}</span>
                    <span className="er-chip er-chip-human">Person only: {stepCount(personSteps)}</span>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        <div className="er-actions">
          <AppLink to="/nonprofits" className="er-btn-secondary">
            See each kit&apos;s step map
          </AppLink>
          <AppLink to="/catalog" className="er-btn-secondary">
            Open the full catalog
          </AppLink>
        </div>
      </section>

      <StatusNote />
    </div>
  );
}
