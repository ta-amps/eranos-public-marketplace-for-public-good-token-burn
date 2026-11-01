import { ErrorAlert } from "../components/ErrorAlert";
import { LIVE_QUEUE_POLL_MS } from "../config";
import type { CatalogResponse, FabricResponse, RequestsResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

function doneLabelForQueue(name: string): string {
  if (name === "eq01") return "Scope planned";
  if (name === "eq02") return "Drafts submitted";
  if (name === "eq03") return "Reviews completed";
  return "Done";
}

export function Fabric() {
  const fabric = useResource<FabricResponse>("/api/fabric", { pollMs: LIVE_QUEUE_POLL_MS });
  const catalog = useResource<CatalogResponse>("/api/catalog", { pollMs: LIVE_QUEUE_POLL_MS });
  const requests = useResource<RequestsResponse>("/api/requests");
  const fabricState = fabric.state;
  const catalogState = catalog.state;
  const requestsState = requests.state;
  const verifiedKitCount = catalogState.status === "ready" ? catalogState.data.kits.length : null;
  const swarm = fabricState.status === "ready" ? fabricState.data.swarm : undefined;

  return (
    <div>
      <section className="er-section">
        <h1>Work queues on Tessera</h1>
        <p className="er-lede">
          Tessera is the shared durable task queue and task objects store underneath Eranos &mdash; workers claim
          durable tasks (things to do), publish checked task objects, and another worker verifies before anything goes
          live. Eranos uses three leased queues on it (<code>eq01</code>, <code>eq02</code>, <code>eq03</code>),
          quarantining unreviewed drafts as <code>surface_only</code> and promoting independently reviewed packages via
          content-addressed SHA-256 blobs and atomic compare-and-set batch writes (<code>eranos.catalog</code> +{" "}
          <code>eranos.index</code>).
        </p>

        {fabricState.status === "loading" && <p className="er-muted">Loading queue telemetry...</p>}
        {fabricState.status === "error" && (
          <ErrorAlert
            title="Error loading queue telemetry"
            message={fabricState.message}
            onRetry={fabric.reload}
          />
        )}
        {fabricState.status === "ready" && (
          <div className="er-grid">
            {fabricState.data.queues.map((q) => (
              <article key={q.name} className="er-card">
                <div className="er-chip-row">
                  <span className="er-chip er-chip-assists">{q.name}</span>
                  {q.label && <span className="er-chip er-chip-drafts">{q.label}</span>}
                  <span className="er-chip er-chip-neutral">Mode: {fabricState.data.plan}</span>
                </div>
                <h2>{q.label ? `${q.name} · ${q.label}` : `Queue ${q.name}`}</h2>
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
                    <dt>{doneLabelForQueue(q.name)}</dt>
                    <dd>{q.done}</dd>
                  </div>
                  {q.dead > 0 && (
                    <div>
                      <dt>Stopped / refused</dt>
                      <dd>{q.dead}</dd>
                    </div>
                  )}
                </dl>
              </article>
            ))}
          </div>
        )}
        {fabricState.status === "ready" && (
          <p className="er-muted er-small">
            Scope planned on <code>eq01</code> counts requests split into buildable parts; kits and cited reports join
            the library only after independent review completes on <code>eq03</code>
            {verifiedKitCount !== null ? (
              <>
                {" "}
                ({verifiedKitCount} two-step verified kits currently published in <code>eranos.catalog</code>).
              </>
            ) : (
              "."
            )}
          </p>
        )}
      </section>

      {swarm && (
        <section className="er-section" data-testid="fabric-swarm">
          <h2>Shared public-good worker swarm on Herma</h2>
          <p className="er-muted">
            Volunteer agents and always-on dedicated baseline workers also claim and complete NGO priority and
            general public-good tasks on Herma (<code>herma.ta-amps.workers.dev/q</code>). Task objects stored on the
            shared queue are reusable building blocks and remain distinct from two-step reviewed Eranos catalog kits until
            independently audited on <code>eq03</code>.
          </p>
          <div className="er-grid">
            <article className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">ngo_priority</span>
                <span className="er-chip er-chip-neutral">Herma /q</span>
              </div>
              <h3>NGO priority queue</h3>
              <dl className="er-dl">
                <div>
                  <dt>Ready</dt>
                  <dd>{swarm.ngo_ready}</dd>
                </div>
                <div>
                  <dt>Leased</dt>
                  <dd>{swarm.ngo_leased}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>{swarm.ngo_done}</dd>
                </div>
              </dl>
            </article>
            <article className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-drafts">public_general</span>
                <span className="er-chip er-chip-neutral">Herma /q</span>
              </div>
              <h3>Public-good capability queue</h3>
              <dl className="er-dl">
                <div>
                  <dt>Ready</dt>
                  <dd>{swarm.general_ready}</dd>
                </div>
                <div>
                  <dt>Leased</dt>
                  <dd>{swarm.general_leased}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>{swarm.general_done}</dd>
                </div>
              </dl>
            </article>
            <article className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-neutral">Swarm fleet</span>
              </div>
              <h3>Workers &amp; shared task objects</h3>
              <dl className="er-dl">
                <div>
                  <dt>Registered volunteer &amp; dedicated workers</dt>
                  <dd>{swarm.registered_workers}</dd>
                </div>
                <div>
                  <dt>Indexed shared-queue task objects</dt>
                  <dd>{swarm.stored_task_objects}</dd>
                </div>
              </dl>
            </article>
          </div>
        </section>
      )}

      {requestsState.status === "error" && (
        <ErrorAlert
          title="Error loading stage contracts"
          message={requestsState.message}
          onRetry={requests.reload}
        />
      )}
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
