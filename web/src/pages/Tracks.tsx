import { DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import type { TracksResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

export function Tracks() {
  const { state, reload } = useResource<TracksResponse>("/api/tracks");

  return (
    <div>
      <section className="er-section">
        <h1>Public-good build tracks</h1>
        <p className="er-lede">
          Tracks live as pure JSON data packs in <code>tracks/&lt;id&gt;/track.json</code>. Adding a new public-good
          domain, step kind, or organization type requires zero Python or TypeScript code changes.
        </p>

        {state.status === "loading" && <p className="er-muted">Loading tracks...</p>}
        {state.status === "error" && (
          <ErrorAlert title="Error loading tracks" message={state.message} onRetry={reload} />
        )}
        {state.status === "ready" && (
          <div className="er-grid">
            {state.data.tracks.map((track) => (
              <article key={track.id} className="er-card">
                <div className="er-chip-row">
                  <DomainBadge domain={track.domain} label={track.domain_label} />
                  <code>{track.id}</code>
                  {track.kit_ready && (
                    <span className="er-chip er-chip-drafts">
                      Catalog kit: {(track.catalog_kit_ids ?? []).join(", ") || "ready"}
                    </span>
                  )}
                  {track.process_ready && <span className="er-chip er-chip-assists">Process build ready</span>}
                </div>
                <h2>{track.title}</h2>
                <p className="er-muted">{track.summary}</p>
                <div>
                  <strong  className="er-font-14">Organizations served:</strong>
                  <ul>
                    {track.organizations.map((org) => (
                      <li key={org.org_type} className="er-muted">
                        <strong>{org.org_type}:</strong> {org.mandate}
                      </li>
                    ))}
                  </ul>
                </div>
                <p className="er-muted">
                  <strong>Allowed deliverable types:</strong> <code>{track.allowed_artifacts.join(", ")}</code>
                </p>
                <p className="er-muted">
                  <strong>Required human-only steps:</strong>{" "}
                  <code>{track.required_human_only.join(", ")}</code>
                </p>
                <div>
                  <strong  className="er-font-14">Lines never crossed:</strong>
                  <ul>
                    {track.never.map((rule) => (
                      <li key={rule} className="er-muted">
                        {rule}
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
