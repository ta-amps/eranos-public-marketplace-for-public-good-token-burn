import { useState } from "react";

import { BoundaryBadge, DomainBadge } from "../components/BoundaryBadge";
import { allSkills, allTools, type CatalogResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

export function Catalog() {
  const { state } = useResource<CatalogResponse>("/api/catalog");
  const [filter, setFilter] = useState<string>("all");

  const domains =
    state.status === "ready" ? Array.from(new Set(state.data.kits.map((k) => k.kit.domain))).sort() : [];

  const kits =
    state.status === "ready"
      ? state.data.kits.filter((k) => filter === "all" || k.kit.domain === filter)
      : [];

  return (
    <div>
      <section className="er-section">
        <h1>Off-the-Shelf NGO Catalog: Skills, Tools, Files &amp; Agentic Processes</h1>
        <p className="er-lede">
          Ready-to-use public-good packages built and tested with donated tokens. Every kit below passed deterministic
          boundary and test-fixture verification on <code>eq02</code> plus independent review (
          <code>drafter ≠ reviewer</code>) on <code>eq03</code> before atomic publication to{" "}
          <code>eranos.catalog</code>.
        </p>

        <div className="er-filter-bar" role="group" aria-label="Filter catalog by domain">
          <button
            type="button"
            className="er-filter-btn"
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            All domains
          </button>
          {domains.map((dom) => (
            <button
              key={dom}
              type="button"
              className="er-filter-btn"
              aria-pressed={filter === dom}
              onClick={() => setFilter(dom)}
            >
              {dom === "anti_exploitation"
                ? "Anti-exploitation NGO"
                : dom === "nonprofit_ops"
                  ? "Nonprofit operations"
                  : dom.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        {state.status === "loading" && <p className="er-muted">Loading verified kits…</p>}
        {state.status === "error" && <p className="er-muted">Error loading catalog: {state.message}</p>}
        {state.status === "ready" && (
          <div className="er-grid">
            {kits.map((entry) => {
              const humanCount = entry.kit.steps.filter((s) => s.boundary === "human_only").length;
              const skills = allSkills(entry.kit);
              const tools = allTools(entry.kit);
              const primaryBoundary = skills[0]?.boundary ?? entry.kit.artifacts[0]?.boundary ?? "assists";
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <span className="er-chip er-chip-neutral">{entry.kit.kit_id}</span>
                    <DomainBadge domain={entry.kit.domain} />
                    <BoundaryBadge boundary={primaryBoundary} />
                  </div>
                  <h2>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h2>
                  <p className="er-muted">{entry.kit.summary}</p>
                  <p className="er-muted">
                    <strong>Organization:</strong> {entry.kit.target_org} · <strong>Kind:</strong>{" "}
                    <code>{entry.kit.deliverable_kind}</code>
                  </p>
                  <p className="er-muted">
                    <strong>Autonomy split:</strong> {entry.kit.steps.length} workflow steps ({humanCount} strictly
                    human-only) · {skills.length} skill(s) · {tools.length} MCP tool(s) ·{" "}
                    {entry.kit.artifacts.length} custom artifact(s)
                  </p>
                  <div className="er-actions" style={{ marginTop: "auto" }}>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`} className="er-btn-secondary">
                      Inspect deliverables, schemas &amp; receipts
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
