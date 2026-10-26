import { BoundaryBadge, DomainBadge } from "../components/BoundaryBadge";
import type { PublishedKit } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

export function KitDetail({ id }: { id: string }) {
  const { state } = useResource<PublishedKit>(`/api/catalog/${encodeURIComponent(id)}`);

  if (state.status === "loading") {
    return <p className="er-muted">Loading kit {id}…</p>;
  }
  if (state.status === "error") {
    return (
      <section className="er-card">
        <h1>Kit unavailable</h1>
        <p className="er-muted">{state.message}</p>
        <p>
          <AppLink to="/catalog">Back to catalog</AppLink>
        </p>
      </section>
    );
  }

  const entry = state.data;
  const { kit, verification } = entry;

  return (
    <div>
      <p className="er-muted" style={{ marginBottom: 12 }}>
        <AppLink to="/catalog">← Verified Catalog</AppLink> / <code>{kit.kit_id}</code>
      </p>

      <section className="er-hero">
        <div className="er-chip-row" style={{ marginBottom: 12 }}>
          <span className="er-chip er-chip-neutral">{kit.kit_id}</span>
          <DomainBadge domain={kit.domain} />
          <BoundaryBadge boundary={kit.skill.boundary} />
          {entry.steward_signoff && (
            <span className="er-chip er-chip-steward">Steward sign-off: {entry.steward_signoff}</span>
          )}
        </div>
        <h1>{kit.title}</h1>
        <p className="er-lede">{kit.summary}</p>
        <p className="er-muted">
          <strong>Target organization:</strong> {kit.target_org} · <strong>Track:</strong>{" "}
          <code>{kit.track_id}</code> · <strong>Catalog version:</strong> v{entry.catalog_version}
        </p>
      </section>

      <section className="er-section">
        <h2>Workflow autonomy map (what agents prepare vs. what people decide)</h2>
        <ul className="er-step-list">
          {kit.steps.map((step) => (
            <li key={step.id} className="er-step-item">
              <div className="er-chip-row" style={{ marginBottom: 6 }}>
                <BoundaryBadge boundary={step.boundary} />
                <strong>{step.title}</strong>
                <span className="er-chip er-chip-neutral">{step.kind}</span>
                <span className="er-muted">Actor: {step.actor}</span>
              </div>
              <p className="er-muted">{step.guidance}</p>
            </li>
          ))}
        </ul>
      </section>

      <div className="er-grid">
        <section className="er-card">
          <h2>Agent Skill Spec · {kit.skill.name}</h2>
          <p className="er-muted">{kit.skill.description}</p>
          <p className="er-muted">
            <strong>Instructions:</strong> {kit.skill.instructions}
          </p>
          <div>
            <strong>Explicitly refuses:</strong>
            <ul>
              {kit.skill.refuses.map((r) => (
                <li key={r} className="er-muted">
                  {r}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="er-card">
          <h2>Read-Only MCP Tool · {kit.tool.name}</h2>
          <p className="er-muted">{kit.tool.description}</p>
          <p className="er-muted">
            <strong>Output fields:</strong> <code>{kit.tool.output_fields.join(", ")}</code>
          </p>
          <pre className="er-code">{JSON.stringify(kit.tool.input_schema, null, 2)}</pre>
        </section>
      </div>

      <div className="er-grid">
        <section className="er-card">
          <h2>Staff operational checklist</h2>
          <ul>
            {kit.checklist.map((item) => (
              <li key={item} className="er-muted">
                {item}
              </li>
            ))}
          </ul>
          <h3>Primary public sources</h3>
          <ul>
            {kit.sources.map((src) => (
              <li key={src.url} className="er-muted">
                <a href={src.url} target="_blank" rel="noreferrer">
                  {src.title}
                </a>{" "}
                (checked {src.checked_date})
              </li>
            ))}
          </ul>
        </section>

        <section className="er-card">
          <h2>Synthetic verification fixtures ({verification.fixture_count})</h2>
          {kit.fixtures.map((fx) => (
            <div key={fx.id} style={{ borderTop: "1px solid var(--er-border)", paddingTop: 10 }}>
              <div className="er-chip-row">
                <code>{fx.id}</code>
                <span className={fx.expected_human_escalation ? "er-chip er-chip-human" : "er-chip er-chip-drafts"}>
                  {fx.expected_human_escalation ? "Escalates to person" : "Routine prep"}
                </span>
              </div>
              <p className="er-muted">
                <strong>{fx.scenario}:</strong> {fx.sample_input}
              </p>
            </div>
          ))}
        </section>
      </div>

      <section className="er-section">
        <h2>Two-step Tessera verification receipts (drafter ≠ reviewer)</h2>
        <dl className="er-dl">
          <div>
            <dt>Drafted on eq02 by</dt>
            <dd>
              {kit.drafted_by} ({kit.drafted_by_key})
            </dd>
          </div>
          <div>
            <dt>Independently reviewed on eq03 by</dt>
            <dd>
              {entry.reviewed_by} ({entry.reviewed_by_key})
            </dd>
          </div>
          <div>
            <dt>Content-addressed blob SHA-256</dt>
            <dd>{entry.blob_sha256}</dd>
          </div>
          <div>
            <dt>eq02 draft receipt</dt>
            <dd>{entry.draft_receipt}</dd>
          </div>
          <div>
            <dt>eq03 review receipt</dt>
            <dd>{entry.review_receipt}</dd>
          </div>
          <div>
            <dt>Reviewer notes</dt>
            <dd>{entry.review_notes}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
