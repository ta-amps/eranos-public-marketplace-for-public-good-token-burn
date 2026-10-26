import type { FabricResponse, RequestsResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

export function Fabric() {
  const fabric = useResource<FabricResponse>("/api/fabric");
  const requests = useResource<RequestsResponse>("/api/requests");
  const fabricState = fabric.state;
  const requestsState = requests.state;

  return (
    <div>
      <section className="er-section">
        <h1>Tessera queues &amp; atomic CAS publication</h1>
        <p className="er-lede">
          Eranos uses three leased queues on Tessera (<code>eq01</code>, <code>eq02</code>, <code>eq03</code>),
          content-addressed SHA-256 blobs, and atomic compare-and-set batch writes (<code>eranos.catalog</code> +{" "}
          <code>eranos.index</code>).
        </p>

        {fabricState.status === "loading" && <p className="er-muted">Loading queue telemetry…</p>}
        {fabricState.status === "error" && <p className="er-muted">Error: {fabricState.message}</p>}
        {fabricState.status === "ready" && (
          <div className="er-grid">
            {fabricState.data.queues.map((q) => (
              <article key={q.name} className="er-card">
                <div className="er-chip-row">
                  <span className="er-chip er-chip-assists">{q.name}</span>
                  <span className="er-chip er-chip-neutral">Mode: {fabricState.data.plan}</span>
                </div>
                <h2>Queue {q.name}</h2>
                <dl className="er-dl">
                  <div>
                    <dt>Ready</dt>
                    <dd>{q.ready}</dd>
                  </div>
                  <div>
                    <dt>Leased</dt>
                    <dd>{q.leased}</dd>
                  </div>
                  <div>
                    <dt>Waiting (Parked)</dt>
                    <dd>{q.waiting}</dd>
                  </div>
                  <div>
                    <dt>Done</dt>
                    <dd>{q.done}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      {requestsState.status === "ready" && (
        <section className="er-section">
          <h2>Stage contracts</h2>
          <div className="er-grid">
            {requestsState.data.stages.map((stage) => (
              <article key={stage.queue} className="er-card">
                <div className="er-chip-row">
                  <code>{stage.queue}</code>
                  <span className="er-chip er-chip-drafts">{stage.effect_class}</span>
                </div>
                <h3>{stage.title}</h3>
                <p className="er-muted">{stage.purpose}</p>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
