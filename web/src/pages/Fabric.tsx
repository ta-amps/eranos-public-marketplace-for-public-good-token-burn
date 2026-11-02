import { ErrorAlert } from "../components/ErrorAlert";
import { LIVE_QUEUE_POLL_MS } from "../config";
import type { CatalogResponse, FabricResponse, RequestsResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

function doneLabelForQueue(name: string): string {
  if (name === "eq01") return "Requests scoped";
  if (name === "eq02") return "Drafts submitted";
  if (name === "eq03") return "Reviews completed";
  return "Done";
}

export function Fabric() {
  const fabric = useResource<FabricResponse>("/api/fabric", { pollMs: LIVE_QUEUE_POLL_MS });
  const catalog = useResource<CatalogResponse>("/api/catalog");
  const requests = useResource<RequestsResponse>("/api/requests");
  const fabricState = fabric.state;
  const catalogState = catalog.state;
  const requestsState = requests.state;
  const verifiedKitCount = catalogState.status === "ready" ? catalogState.data.kits.length : null;
  const swarm = fabricState.status === "ready" ? fabricState.data.swarm : undefined;

  return (
    <div>
      <section className="er-section">
        <h1>Work queues on Teleion Fabric</h1>
        <p className="er-lede">
          Eranos runs on Teleion Fabric, a shared work queue that keeps every Task (a piece of work) and every Task Object (what
          a Task uses or makes) with a record of each step. A request moves through three steps here: planning, making,
          and a check by a different helper. Nothing joins the library until that check passes.
        </p>

        {fabricState.status === "loading" && <p className="er-muted">Loading the queue…</p>}
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
                  {q.label && <span className="er-chip er-chip-drafts">{q.label}</span>}
                </div>
                <h2>{q.label ?? "A step"}</h2>
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
            Requests split into parts are counted in planning; kits and cited reports join the library only after a
            different helper checks them
            {verifiedKitCount !== null ? <> ({verifiedKitCount} checked kits are in the library now).</> : "."}
          </p>
        )}
      </section>

      {swarm && (
        <section className="er-section" data-testid="fabric-swarm">
          <h2>The shared work queue across ta-amps</h2>
          <p className="er-muted">
            AI workers also do Tasks for nonprofits and other public-good groups on a shared queue. Its Task Objects
            are reusable building blocks; they join the Eranos library only after a different helper checks them.
          </p>
          <div className="er-grid">
            <article className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">Nonprofits first</span>
              </div>
              <h3>Tasks for nonprofits</h3>
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
                <span className="er-chip er-chip-drafts">Public good</span>
              </div>
              <h3>Other public-good Tasks</h3>
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
                  <span className="er-chip er-chip-drafts">{stage.title}</span>
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
