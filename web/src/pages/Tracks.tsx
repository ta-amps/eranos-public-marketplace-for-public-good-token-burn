import { DomainBadge } from "../components/BoundaryBadge";
import type { TracksResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

export function Tracks() {
  const { state } = useResource<TracksResponse>("/api/tracks");

  return (
    <div>
      <section className="er-section">
        <h1>Public-good build tracks</h1>
        <p className="er-lede">
          Tracks live as pure JSON data packs in <code>tracks/&lt;id&gt;/track.json</code>. Each track specifies
          which organizations it serves, what agents may draft or assist with, and which step kinds must remain
          strictly human-only.
        </p>

        {state.status === "loading" && <p className="er-muted">Loading tracks…</p>}
        {state.status === "error" && <p className="er-muted">Error loading tracks: {state.message}</p>}
        {state.status === "ready" && (
          <div className="er-grid">
            {state.data.tracks.map((track) => (
              <article key={track.id} className="er-card">
                <div className="er-chip-row">
                  <DomainBadge domain={track.domain} />
                  <code>{track.id}</code>
                </div>
                <h2>{track.title}</h2>
                <p className="er-muted">{track.summary}</p>
                <p className="er-muted">
                  <strong>Organizations served:</strong> {track.organizations.join("; ")}
                </p>
                <div>
                  <strong style={{ fontSize: 14 }}>Agent helps with:</strong>
                  <ul>
                    {track.agent_helps_with.map((item) => (
                      <li key={item} className="er-muted">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <strong style={{ fontSize: 14 }}>People always keep:</strong>
                  <ul>
                    {track.human_must_do.map((item) => (
                      <li key={item} className="er-muted">
                        {item}
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
