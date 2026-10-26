import { useState } from "react";

import { BoundaryBadge, DomainBadge } from "../components/BoundaryBadge";
import type { CatalogResponse, TrackDomain } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

type Filter = "all" | TrackDomain;

export function Catalog() {
  const { state } = useResource<CatalogResponse>("/api/catalog");
  const [filter, setFilter] = useState<Filter>("all");

  const kits =
    state.status === "ready"
      ? state.data.kits.filter((k) => filter === "all" || k.kit.domain === filter)
      : [];

  return (
    <div>
      <section className="er-section">
        <h1>Verified Operational Kit Catalog</h1>
        <p className="er-lede">
          Every kit below passed deterministic boundary verification on <code>eq02</code> and independent review
          (<code>drafter ≠ reviewer</code>) on <code>eq03</code> before atomic publication to{" "}
          <code>eranos.catalog</code>.
        </p>

        <div className="er-filter-bar" role="group" aria-label="Filter catalog by domain">
          <button
            type="button"
            className="er-filter-btn"
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            All kits
          </button>
          <button
            type="button"
            className="er-filter-btn"
            aria-pressed={filter === "anti_exploitation"}
            onClick={() => setFilter("anti_exploitation")}
          >
            Anti-exploitation NGO kits
          </button>
          <button
            type="button"
            className="er-filter-btn"
            aria-pressed={filter === "nonprofit_ops"}
            onClick={() => setFilter("nonprofit_ops")}
          >
            Nonprofit operations tools
          </button>
        </div>

        {state.status === "loading" && <p className="er-muted">Loading verified kits…</p>}
        {state.status === "error" && <p className="er-muted">Error loading catalog: {state.message}</p>}
        {state.status === "ready" && (
          <div className="er-grid">
            {kits.map((entry) => {
              const humanCount = entry.kit.steps.filter((s) => s.boundary === "human_only").length;
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <span className="er-chip er-chip-neutral">{entry.kit.kit_id}</span>
                    <DomainBadge domain={entry.kit.domain} />
                    <BoundaryBadge boundary={entry.kit.skill.boundary} />
                  </div>
                  <h2>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h2>
                  <p className="er-muted">{entry.kit.summary}</p>
                  <p className="er-muted">
                    <strong>Organization:</strong> {entry.kit.target_org}
                  </p>
                  <p className="er-muted">
                    <strong>Autonomy split:</strong> {entry.kit.steps.length} workflow steps ({humanCount} strictly
                    human-only) · {entry.kit.sources.length} cited source(s)
                  </p>
                  <div className="er-actions" style={{ marginTop: "auto" }}>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`} className="er-btn-secondary">
                      Inspect skill, MCP schema &amp; receipts
                    </AppLink>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
