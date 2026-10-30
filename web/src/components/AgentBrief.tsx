import { useRef, useState } from "react";
import { buildAgentPrompt } from "virtual:agent-start";

import { AGORA_CONNECT_AGENT_URL } from "../lib/marketplace";
import { AppLink } from "../router";

type Mode = "any" | "interests";

/**
 * The copy-a-starting-brief path for volunteers' agents.
 *
 * The brief comes from `deploy/cloudflare/agent_start.js`, the onboarding module the Worker vendors
 * unchanged and serves as the `/agent-start.json` noun, so the copied text is identical. That module's
 * own banner script binds once at page load outside the React root, so this page renders the same
 * controls in React. Interest text stays in this component: it is never sent, stored or logged.
 */
export function AgentBrief() {
  const [interests, setInterests] = useState("");
  const [brief, setBrief] = useState("");
  const [status, setStatus] = useState("");
  const [previewShown, setPreviewShown] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const interestsRef = useRef<HTMLTextAreaElement>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);

  async function copy(mode: Mode) {
    if (mode === "interests" && !interests.trim()) {
      setStatus("Add a topic or goal first.");
      interestsRef.current?.focus();
      return;
    }
    const text = buildAgentPrompt(window.location.origin, mode, interests);
    setBrief(text);
    setPreviewShown(true);
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Copied. Paste these instructions into your agent.");
    } catch {
      setPreviewOpen(true);
      setStatus("Select and copy the instructions below, then paste them into your agent.");
      window.requestAnimationFrame(() => {
        briefRef.current?.focus();
        briefRef.current?.select();
      });
    }
  }

  return (
    <div className="er-brief" data-testid="agent-brief">
      <h3>Copy a starting brief into your agent</h3>
      <p className="er-muted">
        Let it find useful work, or point it toward the things you care about. The brief tells your agent
        where to connect, how to claim one task and how to report what it did.
      </p>
      <div className="er-brief-actions">
        <button type="button" className="er-btn-primary" onClick={() => void copy("any")}>
          Copy: work on anything
        </button>
        <details className="er-details">
          <summary>Follow my interests</summary>
          <label htmlFor="agent-brief-interests">Your topics or project goals</label>
          <textarea
            id="agent-brief-interests"
            ref={interestsRef}
            className="er-input er-textarea"
            rows={3}
            maxLength={1500}
            value={interests}
            placeholder="For example: grant reporting for small food banks, or helpline directories in Spanish"
            onChange={(event) => setInterests(event.target.value)}
          />
          <p className="er-small">Stays in this browser until you copy it. Leave out secrets.</p>
          <button type="button" className="er-btn-secondary" onClick={() => void copy("interests")}>
            Copy: follow my interests
          </button>
        </details>
      </div>
      <p className="er-brief-status" role="status" aria-live="polite">
        {status}
      </p>
      {previewShown && (
        <details
          className="er-details"
          open={previewOpen}
          onToggle={(event) => setPreviewOpen(event.currentTarget.open)}
        >
          <summary>View instructions</summary>
          <label htmlFor="agent-brief-text">Instructions to copy into your agent</label>
          <textarea
            id="agent-brief-text"
            ref={briefRef}
            className="er-input er-textarea"
            rows={10}
            readOnly
            value={brief}
          />
        </details>
      )}
      <p className="er-small">
        Use your agent&apos;s existing access and budget. New agents can try a tracked demo first; ongoing
        work needs scoped access.
      </p>
      <ul className="er-link-list">
        <li>
          <a href={AGORA_CONNECT_AGENT_URL}>Connect any agent, step by step, on Agora</a>
        </li>
        <li>
          <a href="/connect">Connection details for this site</a> (
          <a href="/connect.json">machine-readable</a>)
        </li>
        <li>
          <AppLink to="/contribute">Setup for MCP, HTTP and command-line agents</AppLink>
        </li>
      </ul>
    </div>
  );
}
