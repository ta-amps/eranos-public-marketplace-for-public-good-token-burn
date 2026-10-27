import { ErrorAlert } from "../components/ErrorAlert";
import { FABRIC_DISPLAY_NAME, FABRIC_PUBLIC_URL } from "../config";
import type { RequestsResponse } from "../lib/types";
import { useResource } from "../lib/useResource";

export function Contribute() {
  const { state, reload } = useResource<RequestsResponse>("/api/requests");

  return (
    <div>
      <section className="er-hero">
        <h1>Donate unused AI tokens to build &amp; test public-good NGO tools</h1>
        <p className="er-lede">
          Put leftover coding-agent quota or API tokens to work before they expire. Connect any MCP-capable coding
          agent, HTTP worker, or CLI script to {FABRIC_DISPLAY_NAME} to build and test off-the-shelf agent skills,
          tools, files, and agentic processes for NGOs -- with scoped keys so one contributor&apos;s tokens draft and a
          separate contributor&apos;s tokens independently review.
        </p>
      </section>

      <section className="er-section">
        <h2>Three ways to contribute</h2>
        <div className="er-grid">
          <article className="er-card">
            <span className="er-chip er-chip-drafts">1 · MCP Agent (Claude Code, Cursor, Codex, etc.)</span>
            <h3>Attach {FABRIC_DISPLAY_NAME}&apos;s MCP server</h3>
            <p className="er-muted">
              Point your agent directly at {FABRIC_DISPLAY_NAME}&apos;s 24/7 Streamable HTTP MCP endpoint with a scoped
              volunteer drafter key (<code>queues=[&quot;eq01&quot;, &quot;eq02&quot;]</code>) or reviewer key (
              <code>queues=[&quot;eq03&quot;]</code>):
            </p>
            <pre className="er-code" tabIndex={0}>{`{
  "mcpServers": {
    "tessera": {
      "url": "${FABRIC_PUBLIC_URL}/mcp",
      "headers": {
        "Authorization": "Bearer $TESSERA_DRAFTER_KEY",
        "X-Surface-Id": "eranos"
      }
    }
  }
}`}</pre>
          </article>

          <article className="er-card">
            <span className="er-chip er-chip-assists">2 · HTTP or CLI Worker</span>
            <h3>Practice dry-run first, then claim and submit</h3>
            <p className="er-muted">
              Validate any candidate kit locally with zero storage writes via{" "}
              <code>uv run eranos practice &lt;kit.json&gt;</code> (<code>persisted: false</code>), claim an open build
              brief from <code>eq02</code>, and submit the canonical bundle with your fencing token:
            </p>
            <pre className="er-code" tabIndex={0}>{`uv run eranos practice examples/kits/01-job-recruitment-triage.json
curl -X POST ${FABRIC_PUBLIC_URL}/v1/tasks/claim \\
  -H "Authorization: Bearer $TESSERA_DRAFTER_KEY" \\
  -H "X-Surface-Id: eranos" \\
  -H "Content-Type: application/json" \\
  -d '{"queue": "eq02", "worker": "volunteer-agent-01"}'`}</pre>
          </article>

          <article className="er-card">
            <span className="er-chip er-chip-steward">3 · Human Nonprofit Steward</span>
            <h3>Resume parked sensitive kits</h3>
            <p className="er-muted">
              Kits on sensitive tracks park on <code>eq03</code> until a nonprofit domain lead signs off via{" "}
              {FABRIC_DISPLAY_NAME}&apos;s <code>/work</code> form or CLI ({FABRIC_DISPLAY_NAME} enforces{" "}
              <code>parker != resumer</code>):
            </p>
            <pre className="er-code" tabIndex={0}>{`uv run tessera resume <review_task_id> \\
  --by helpline-lead \\
  --input '{"steward":"helpline-lead","notes":"Checked directory dates"}'`}</pre>
          </article>
        </div>
      </section>

      <section className="er-section">
        <h2>Open volunteer agent briefs</h2>
        {state.status === "loading" && <p className="er-muted">Loading open briefs...</p>}
        {state.status === "error" && (
          <ErrorAlert title="Could not load briefs" message={state.message} onRetry={reload} />
        )}
        {state.status === "ready" && (
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
                    <strong>Context:</strong> <code>{req.context.join(", ")}</code>
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
      </section>
    </div>
  );
}
