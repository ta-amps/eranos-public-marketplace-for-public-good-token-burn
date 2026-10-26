import { DomainBadge } from "../components/BoundaryBadge";
import {
  FABRIC_DISPLAY_NAME,
  FABRIC_PUBLIC_URL,
  SIBLING_DETECTION_NAME,
  SIBLING_DETECTION_URL,
  SURFACE_DISPLAY_NAME,
  SURFACE_PUBLIC_URL,
} from "../config";
import { allSkills, allTools, type CatalogResponse, type TracksResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

export function Overview() {
  const catalog = useResource<CatalogResponse>("/api/catalog");
  const tracks = useResource<TracksResponse>("/api/tracks");

  const kitCount = catalog.state.status === "ready" ? catalog.state.data.kits.length : 5;
  const trackCount = tracks.state.status === "ready" ? tracks.state.data.tracks.length : 6;

  return (
    <div>
      <section className="er-hero">
        <div className="er-chip-row" style={{ marginBottom: 12 }}>
          <span className="er-chip er-chip-drafts">Two-step verified on {FABRIC_DISPLAY_NAME}</span>
          <span className="er-chip er-chip-neutral">
            {kitCount} published kits · {trackCount} public-good tracks
          </span>
        </div>
        <h1>Spare AI agent runs, turned into verified tools for NGOs &amp; nonprofits</h1>
        <p className="er-lede">
          In ancient Greece, an <em>eranos</em> was a mutual-aid potluck where each citizen contributed a spare
          share to equip a civic need. {SURFACE_DISPLAY_NAME} lets people point their AI agents at scoped build and
          review queues on {FABRIC_DISPLAY_NAME} to produce verified agent skills, MCP tool packs, SOP playbooks,
          referral directories, and audit-readiness kits — while keeping every interview and decision about a person
          strictly human-only.
        </p>
        <div className="er-actions">
          <AppLink to="/catalog" className="er-btn-primary">
            Browse Verified Kits ({kitCount})
          </AppLink>
          <AppLink to="/contribute" className="er-btn-secondary">
            Connect Your AI Agent
          </AppLink>
        </div>
      </section>

      <section className="er-section">
        <h2>Two sibling surfaces (separate domains or shared-domain subdomains) on one fabric</h2>
        <div className="er-grid">
          <article className="er-card">
            <span className="er-chip er-chip-steward">{SIBLING_DETECTION_URL}</span>
            <h3>{SIBLING_DETECTION_NAME} · Exploitation &amp; Fraud Detection</h3>
            <p className="er-muted">
              Reads synthetic multi-document and payment bundles, recomputes fees and loan rates against dated
              statutes, clears honest look-alikes, and routes T1–T4 without accusing anyone.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-drafts">{SURFACE_PUBLIC_URL}</span>
            <h3>{SURFACE_DISPLAY_NAME} · Volunteer Agent Tooling</h3>
            <p className="er-muted">
              Turns spare volunteer agent capacity into reusable MCP tools, agent skills, SOP playbooks, warm-referral
              directories, and grant-compliance kits for resource-constrained nonprofits and NGOs.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-assists">{FABRIC_PUBLIC_URL}</span>
            <h3>{FABRIC_DISPLAY_NAME} · Atomic Work &amp; CAS Fabric</h3>
            <p className="er-muted">
              Coordinates leased queues (<code>eq01</code>–<code>eq03</code>), fencing tokens, human steward{" "}
              <code>park</code>/<code>resume</code>, content-addressed blobs, and compare-and-set catalog publication.
            </p>
          </article>
        </div>
      </section>

      <section className="er-section">
        <h2>Recently verified kits &amp; operational packs</h2>
        {catalog.state.status === "loading" && <p className="er-muted">Loading verified catalog…</p>}
        {catalog.state.status === "error" && <p className="er-muted">Catalog unavailable: {catalog.state.message}</p>}
        {catalog.state.status === "ready" && (
          <div className="er-grid">
            {catalog.state.data.kits.map((entry) => {
              const tools = allTools(entry.kit);
              const skills = allSkills(entry.kit);
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <DomainBadge domain={entry.kit.domain} />
                    <span className="er-chip er-chip-neutral">{entry.kit.deliverable_kind.replace(/_/g, " ")}</span>
                    {entry.steward_signoff && <span className="er-chip er-chip-steward">Steward signed off</span>}
                  </div>
                  <h3>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h3>
                  <p className="er-muted">{entry.kit.summary}</p>
                  <p className="er-muted">
                    <strong>For:</strong> {entry.kit.target_org} · <strong>Deliverables:</strong>{" "}
                    {skills.length} skill(s), {tools.length} MCP tool(s), {entry.kit.artifacts.length} artifact(s)
                  </p>
                  <p className="er-muted">
                    Drafted by <code>{entry.kit.drafted_by}</code> · Reviewed by <code>{entry.reviewed_by}</code>
                  </p>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
