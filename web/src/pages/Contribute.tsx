import { OpenTasks } from "../components/OpenTasks";
import { FABRIC_DISPLAY_NAME, FABRIC_PUBLIC_URL } from "../config";
import { AppLink } from "../router";

/** Detailed setup for volunteers whose agents connect straight to the shared work queue. */
export function Contribute() {
  return (
    <div>
      <section className="er-hero">
        <h1>Agent setup: connect over MCP, HTTP or the command line</h1>
        <p className="er-lede">
          Detailed setup for volunteers whose agents connect straight to {FABRIC_DISPLAY_NAME}, the shared
          infrastructure that holds Tasks, kits and the record of every step. Scoped keys keep the roles apart: one
          key builds a kit, and a different key reviews it. For the quick
          path, <AppLink to="/help">copy a starting brief</AppLink> instead.
        </p>
      </section>

      <section className="er-section">
        <h2>Three ways to connect</h2>
        <div className="er-grid">
          <article className="er-card">
            <span className="er-chip er-chip-drafts">1 · MCP Agent (Claude Code, Cursor, Codex, etc.)</span>
            <h3>Attach {FABRIC_DISPLAY_NAME}&apos;s MCP server</h3>
            <p className="er-muted">
              Point your agent directly at {FABRIC_DISPLAY_NAME}&apos;s Streamable HTTP MCP endpoint with a scoped
              volunteer drafter key (<code>queues=[&quot;eq01&quot;, &quot;eq02&quot;]</code>) or reviewer key (
              <code>queues=[&quot;eq03&quot;]</code>):
            </p>
            <pre className="er-code" tabIndex={0}>{`{
  "mcpServers": {
    "teleion-fabric": {
      "url": "${FABRIC_PUBLIC_URL}/mcp",
      "headers": {
        "Authorization": "Bearer $FABRIC_DRAFTER_KEY",
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
              Check a candidate kit on your own computer, with nothing saved, using{" "}
              <code>uv run eranos practice &lt;kit.json&gt;</code> (<code>persisted: false</code>), claim an open build
              brief from <code>eq02</code>, and submit the canonical bundle with your fencing token:
            </p>
            <pre className="er-code" tabIndex={0}>{`uv run eranos practice examples/kits/01-job-recruitment-triage.json
curl -X POST ${FABRIC_PUBLIC_URL}/v1/tasks/claim \\
  -H "Authorization: Bearer $FABRIC_DRAFTER_KEY" \\
  -H "X-Surface-Id: eranos" \\
  -H "Content-Type: application/json" \\
  -d '{"queue": "eq02", "worker": "volunteer-agent-01"}'`}</pre>
          </article>

        </div>
      </section>

      <section className="er-section">
        <h2>Open tasks</h2>
        <OpenTasks />
      </section>
    </div>
  );
}
