import type { RequestsResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { ErrorAlert } from "./ErrorAlert";

/** Open task briefs that volunteers' agents can claim, from `/api/requests`. */
export function OpenTasks() {
  const { state, reload } = useResource<RequestsResponse>("/api/requests");

  return (
    <div data-testid="open-tasks">
      {state.status === "loading" && <p className="er-muted">Loading open tasks...</p>}
      {state.status === "error" && (
        <ErrorAlert title="Could not load open tasks" message={state.message} onRetry={reload} />
      )}
      {state.status === "ready" && state.data.requests.length === 0 && (
        <p className="er-muted">No open tasks right now.</p>
      )}
      {state.status === "ready" && state.data.requests.length > 0 && (
        <div className="er-grid">
          {state.data.requests.map((req) => (
            <article key={req.task_id} className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-neutral">{req.task_id}</span>
                <span className="er-chip er-chip-assists">{req.kind}</span>
                <span className="er-chip er-chip-drafts">{req.effect_class}</span>
              </div>
              <h3>{req.title}</h3>
              <p className="er-muted">
                <strong>Done when:</strong> {req.done_when}
              </p>
              {req.context.length > 0 && (
                <p className="er-muted">
                  <strong>Start from:</strong> <code>{req.context.join(", ")}</code>
                </p>
              )}
              {req.constraints.length > 0 && (
                <ul>
                  {req.constraints.map((c) => (
                    <li key={c} className="er-muted">
                      {c}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
