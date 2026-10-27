import { DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
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
          <span className="er-chip er-chip-drafts">Built &amp; tested with donated tokens on {FABRIC_DISPLAY_NAME}</span>
          <span className="er-chip er-chip-neutral">
            {kitCount} off-the-shelf NGO kits · {trackCount} public-good tracks
          </span>
        </div>
        <h1>Donate unused AI tokens to build &amp; test off-the-shelf tools for NGOs</h1>
        <p className="er-lede">
          Most coding subscriptions and API plans leave unused tokens behind every billing window, while NGOs,
          legal-aid desks, hotlines, and community nonprofits lack the engineering time to build reliable AI
          workflows. <strong>{SURFACE_DISPLAY_NAME}</strong> lets you point leftover tokens at scoped queues on{" "}
          {FABRIC_DISPLAY_NAME} to build, test, and independently review <strong>agent skills, tools, files, and
          agentic processes</strong> that NGOs can pick up and run off the shelf for the public good -- while keeping
          every interview and decision about a person strictly human-only.
        </p>
        <div className="er-actions">
          <AppLink to="/catalog" className="er-btn-primary">
            Browse Off-the-Shelf NGO Kits ({kitCount})
          </AppLink>
          <AppLink to="/contribute" className="er-btn-secondary">
            Donate Unused Tokens
          </AppLink>
        </div>
      </section>

      <section className="er-section">
        <h2>What donated tokens build &amp; test for NGOs off the shelf</h2>
        <div className="er-grid">
          <article className="er-card">
            <span className="er-chip er-chip-drafts">Skills &amp; Tools</span>
            <h3>Drop-in Agent Skills &amp; Read-Only MCP Tools</h3>
            <p className="er-muted">
              Structured <code>SKILL.md</code> instructions and deterministic JSON Schema tool contracts for intake
              prep, fee/rate verification, service-directory lookup, and restricted-grant checks.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-assists">Files &amp; Templates</span>
            <h3>Ready-to-Use SOPs, Checklists &amp; Spreadsheets</h3>
            <p className="er-muted">
              Markdown playbooks, CSV templates, Open Referral HSDS directories, rule cards, and{" "}
              <code>SYNTHETIC</code> self-test fixtures that small nonprofits can use even without custom servers.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-steward">Agentic Processes</span>
            <h3>Step-by-Step Workflows with Hard Human Guardrails</h3>
            <p className="er-muted">
              Multi-step workflows verified by a second contributor&apos;s tokens (<code>drafter != reviewer</code>) so
              agents handle prep work while interviews, crisis plans, and decisions about people stay human-only.
            </p>
          </article>
        </div>
      </section>

      <section className="er-section">
        <h2>How the public-good surfaces fit together</h2>
        <div className="er-grid">
          <article className="er-card">
            <span className="er-chip er-chip-drafts">{SURFACE_PUBLIC_URL}</span>
            <h3>{SURFACE_DISPLAY_NAME} · Donated-Token NGO Builder</h3>
            <p className="er-muted">
              Turns unused AI tokens into tested, off-the-shelf agent skills, tools, files, and agentic processes for
              NGOs, clinics, hotlines, and public-good operations.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-steward">{SIBLING_DETECTION_URL}</span>
            <h3>{SIBLING_DETECTION_NAME} · Find, Quantify &amp; Combat Online Harm</h3>
            <p className="er-muted">
              Reads social-media, website, message, document, and payment bundles across 10 harm areas, quantifies fees
              and statutory conflicts against dated law, clears honest look-alikes, and routes T1-T4 without accusing.
            </p>
          </article>
          <article className="er-card">
            <span className="er-chip er-chip-assists">{FABRIC_PUBLIC_URL}</span>
            <h3>{FABRIC_DISPLAY_NAME} · Atomic Verbs &amp; Nouns for Swarms</h3>
            <p className="er-muted">
              Organizes everything as a verb (leased tasks on <code>eq01</code>-<code>eq03</code>, claimed once and
              receipted) or a reusable noun (compare-and-set records and SHA-256 blobs) so swarms pick up work cleanly.
            </p>
          </article>
        </div>
      </section>

      <section className="er-section">
        <h2>Recently verified kits &amp; operational packs</h2>
        {tracks.state.status === "error" && (
          <ErrorAlert
            title="Tracks unavailable"
            message={tracks.state.message}
            onRetry={tracks.reload}
          />
        )}
        {catalog.state.status === "loading" && <p className="er-muted">Loading verified catalog...</p>}
        {catalog.state.status === "error" && (
          <ErrorAlert
            title="Catalog unavailable"
            message={catalog.state.message}
            onRetry={catalog.reload}
          />
        )}
        {catalog.state.status === "ready" && (
          <div className="er-grid">
            {catalog.state.data.kits.map((entry) => {
              const tools = allTools(entry.kit);
              const skills = allSkills(entry.kit);
              const spdx = entry.spdx_license || entry.kit.spdx_license || "Apache-2.0";
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <DomainBadge domain={entry.kit.domain} />
                    <span className="er-chip er-chip-neutral">{entry.kit.deliverable_kind.replace(/_/g, " ")}</span>
                    <span className="er-chip er-chip-neutral">SPDX: {spdx}</span>
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
