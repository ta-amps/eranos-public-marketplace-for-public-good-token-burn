import { useEffect, useState } from "react";

import { ErrorAlert } from "../components/ErrorAlert";
import type { RequestStatusPayload } from "../lib/requestStatus";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

const STAGE_LABELS = [
  "1. Sort & split",
  "2. Queue & build",
  "3. Independent review",
  "4. Steward & kit ready",
] as const;

export function RequestStatus({ id }: { id: string }) {
  const resource = useResource<RequestStatusPayload>(`/api/requests/${encodeURIComponent(id)}`);
  const [visibleStage, setVisibleStage] = useState<number>(4);
  const [replaying, setReplaying] = useState<boolean>(false);

  useEffect(() => {
    if (!replaying) return;
    if (visibleStage >= 4) {
      setReplaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setVisibleStage((prev) => Math.min(4, prev + 1));
    }, 1350);
    return () => window.clearTimeout(timer);
  }, [replaying, visibleStage]);

  function startReplay() {
    setVisibleStage(1);
    setReplaying(true);
  }

  function showAll() {
    setReplaying(false);
    setVisibleStage(4);
  }

  if (resource.state.status === "loading") {
    return (
      <section className="er-section">
        <p className="er-muted">Loading live request status for {id}...</p>
      </section>
    );
  }

  if (resource.state.status === "error") {
    return (
      <section className="er-section">
        <ErrorAlert
          title="Request status unavailable"
          message={resource.state.message}
          onRetry={resource.reload}
        />
        <div className="er-actions">
          <AppLink to="/requests/REQ-INTAKE-07" className="er-btn-primary">
            Open showcase request REQ-INTAKE-07
          </AppLink>
          <AppLink to="/nonprofits" className="er-btn-secondary">
            Back to For nonprofits
          </AppLink>
        </div>
      </section>
    );
  }

  const req = resource.state.data;

  return (
    <div className="er-req-page" data-testid="request-status-page">
      <section className="er-hero er-req-hero" aria-labelledby="req-status-title" id="request-header">
        <div className="er-req-topbar">
          <div className="er-chip-row">
            <span className="er-chip er-chip-drafts">Request {req.request_id}</span>
            <span className="er-chip er-chip-assists">
              Status: {req.status === "delivered" ? "Reviewed & delivered" : "Queued on Tessera"}
            </span>
            <span className="er-chip er-chip-neutral">{req.organization_type}</span>
          </div>
          <div className="er-req-controls" role="group" aria-label="Execution replay controls">
            <button
              type="button"
              className="er-btn-secondary"
              onClick={startReplay}
              data-testid="replay-lifecycle"
            >
              {replaying ? "Replaying live steps..." : "Replay step-by-step"}
            </button>
            {visibleStage < 4 && (
              <button type="button" className="er-btn-primary" onClick={showAll}>
                Show all 4 steps
              </button>
            )}
          </div>
        </div>

        <h1 id="req-status-title">What happens to this nonprofit request</h1>
        <figure className="er-need er-req-quote" data-testid="submitted-need">
          <figcaption>Plain-words request submitted on /nonprofits</figcaption>
          <blockquote>{req.plain_need}</blockquote>
        </figure>
        <p className="er-small er-mt-10" data-testid="request-privacy-guarantee">
          <strong>Privacy boundary:</strong> {req.privacy_guarantee}
        </p>

        <ol className="er-req-stepper" aria-label="Request progress stages">
          {STAGE_LABELS.map((label, idx) => {
            const stepNum = idx + 1;
            const active = visibleStage >= stepNum;
            return (
              <li
                key={label}
                className={active ? "er-req-step-pill is-active" : "er-req-step-pill"}
              >
                <button
                  type="button"
                  className="er-req-step-btn"
                  onClick={() => {
                    setReplaying(false);
                    setVisibleStage(stepNum);
                  }}
                >
                  {label}
                </button>
              </li>
            );
          })}
        </ol>
      </section>

      {visibleStage >= 1 && (
        <section
          className="er-section er-req-band"
          id="step-split"
          aria-labelledby="split-heading"
          data-testid="step-split"
        >
          <div className="er-req-band-head">
            <div>
              <span className="er-chip er-chip-drafts">First step · Sort and split</span>
              <h2 id="split-heading">1. First step: sort and split into public research vs. local kit</h2>
            </div>
            <code className="er-small">
              queue {req.split.queue} · verb {req.split.verb} · receipt {req.split.receipt.slice(0, 12)}…
            </code>
          </div>

          <div className="er-req-grid-2">
            <article className="er-card er-lane-card er-lane-private" id="private-lane" data-testid="private-lane">
              <div className="er-chip-row">
                <span className="er-chip er-chip-human">{req.split.private_lane.label}</span>
                <span className="er-chip er-chip-neutral">{req.split.private_lane.policy}</span>
              </div>
              <h3>Work on the nonprofit&apos;s own files</h3>
              <ul className="er-plain-list">
                {req.split.private_lane.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <div className="er-lane-outcome er-lane-outcome-private">
                <strong>Outcome: {req.split.private_lane.outcome_title}</strong>
                <p className="er-small">{req.split.private_lane.outcome_detail}</p>
              </div>
            </article>

            <article className="er-card er-lane-card er-lane-public" id="public-lane" data-testid="public-lane">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">{req.split.public_lane.label}</span>
                <span className="er-chip er-chip-neutral">{req.split.public_lane.policy}</span>
              </div>
              <h3>Public research answered &amp; cited</h3>
              <ul className="er-plain-list">
                {req.split.public_lane.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <div className="er-lane-outcome er-lane-outcome-public">
                <strong>Back to the nonprofit: {req.split.public_lane.outcome_title}</strong>
                <ul className="er-req-checks">
                  {req.split.public_lane.checks.map((chk) => (
                    <li key={chk}>✓ {chk}</li>
                  ))}
                </ul>
              </div>
            </article>
          </div>
        </section>
      )}

      {visibleStage >= 2 && (
        <section
          className="er-section er-req-band"
          id="step-build"
          aria-labelledby="build-heading"
          data-testid="step-build"
        >
          <div className="er-req-band-head">
            <div>
              <span className="er-chip er-chip-assists">Second step · Claim, build &amp; test</span>
              <h2 id="build-heading">
                2. Claimed from Tessera queue: only one agent works on it at a time
              </h2>
            </div>
            <code className="er-small">
              queue {req.queue_build.queue} · fencing token #{req.queue_build.fencing_token} · lease{" "}
              {req.queue_build.lease_minutes}m
            </code>
          </div>

          <div className="er-req-grid-2">
            <article className="er-card" id="lease-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-drafts">Exclusive worker lease</span>
                <span className="er-chip er-chip-neutral">{req.queue_build.harness}</span>
              </div>
              <h3>Worker: {req.queue_build.worker_id}</h3>
              <p className="er-muted">
                Lifecycle: <code>claim · do · report</code>. While this {req.queue_build.lease_minutes}-minute
                fenced lease is active, only this worker can submit for <code>{req.kit_id}</code>, and every
                step gets a cryptographic SHA-256 receipt.
              </p>
              <dl className="er-dl">
                <div>
                  <dt>Claim receipt</dt>
                  <dd>{req.queue_build.claim_receipt.slice(0, 20)}…</dd>
                </div>
                <div>
                  <dt>Submitted build receipt</dt>
                  <dd>{req.queue_build.build_receipt.slice(0, 20)}…</dd>
                </div>
              </dl>
            </article>

            <article className="er-card" id="pieces-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">Reused from Seed Packs</span>
                <span className="er-chip er-chip-drafts">Tested on synthetic cases</span>
              </div>
              <h3>Assembled kit pieces ({req.kit_id})</h3>
              <ul className="er-piece-grid" aria-label="Checked kit pieces">
                {req.queue_build.reused_pieces.map((piece) => (
                  <li key={piece.name} className="er-piece-pill">
                    <span className="er-piece-name">
                      <span
                        className={
                          piece.kind === "noun" ? "er-chip er-chip-assists" : "er-chip er-chip-human"
                        }
                      >
                        {piece.kind}
                      </span>{" "}
                      {piece.name}
                    </span>
                    <span className="er-piece-check">✓ {piece.status}</span>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </section>
      )}

      {visibleStage >= 3 && (
        <section
          className="er-section er-req-band"
          id="step-review"
          aria-labelledby="review-heading"
          data-testid="step-review"
        >
          <div className="er-req-band-head">
            <div>
              <span className="er-chip er-chip-steward">Third step · Two-step verification</span>
              <h2 id="review-heading">
                3. Independent verification: the builder can never approve its own kit
              </h2>
            </div>
            <code className="er-small">
              queue {req.independent_review.queue} · {req.independent_review.rule}
            </code>
          </div>

          <div className="er-req-grid-2">
            <article
              className="er-card er-review-card er-review-refused"
              id="refused-card"
              data-testid="self-approval-refused"
            >
              <div className="er-chip-row">
                <span className="er-chip er-chip-human">
                  ✗ HTTP {req.independent_review.self_approval_refusal.http_status} Refused
                </span>
                <span className="er-chip er-chip-neutral">
                  {req.independent_review.self_approval_refusal.actor} ·{" "}
                  {req.independent_review.self_approval_refusal.role}
                </span>
              </div>
              <h3>{req.independent_review.self_approval_refusal.reason}</h3>
              <p className="er-muted">
                Tessera enforces independent review across both worker ID and key ID. When the builder tries
                to approve its own draft, the queue refuses and logs an immutable refusal receipt.
              </p>
              <p className="er-small">
                Refusal receipt:{" "}
                <code>{req.independent_review.self_approval_refusal.receipt.slice(0, 24)}…</code>
              </p>
            </article>

            <article
              className="er-card er-review-card er-review-approved"
              id="approved-card"
              data-testid="reviewer-approved"
            >
              <div className="er-chip-row">
                <span className="er-chip er-chip-drafts">✓ Approved by independent volunteer</span>
                <span className="er-chip er-chip-neutral">
                  {req.independent_review.reviewer_approval.actor}
                </span>
              </div>
              <h3>Verified by a different volunteer&apos;s agent</h3>
              <p className="er-muted">{req.independent_review.reviewer_approval.summary}</p>
              <p className="er-small">
                Review receipt:{" "}
                <code>{req.independent_review.reviewer_approval.receipt.slice(0, 24)}…</code> (
                {req.independent_review.reviewer_approval.checks_passed}/8 checks passed)
              </p>
            </article>
          </div>

          <details className="er-details er-mt-12" id="wire-transcript">
            <summary>View recorded worker &amp; Tessera queue transcript</summary>
            <pre className="er-code er-mt-10">{req.independent_review.cli_transcript.join("\n")}</pre>
          </details>
        </section>
      )}

      {visibleStage >= 4 && (
        <section
          className="er-section er-req-band"
          id="step-ready"
          aria-labelledby="ready-heading"
          data-testid="step-ready"
        >
          <div className="er-req-band-head">
            <div>
              <span className="er-chip er-chip-steward">Fourth step · Steward sign-off &amp; delivery</span>
              <h2 id="ready-heading">4. Human steward sign-off &amp; free, reviewed deliverables</h2>
            </div>
            <code className="er-small">
              steward {req.steward_and_delivery.steward_id} · receipt{" "}
              {req.steward_and_delivery.steward_receipt.slice(0, 12)}…
            </code>
          </div>

          <div className="er-req-grid-2">
            <article className="er-card" id="delivered-kit-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-steward">
                  {req.steward_and_delivery.steward_signed_off
                    ? "✓ Steward signed off"
                    : "Awaiting steward sign-off"}
                </span>
                <span className="er-chip er-chip-drafts">Open license: Apache-2.0</span>
              </div>
              <h3>
                {req.kit_id}: {req.kit_title}
              </h3>
              <p className="er-muted">{req.steward_and_delivery.steward_note}</p>
              <div className="er-actions er-mt-auto">
                <AppLink
                  to={req.steward_and_delivery.catalog_path}
                  className="er-btn-primary"
                  id="open-published-kit"
                  data-testid="open-published-kit"
                >
                  Open reviewed kit ({req.kit_id})
                </AppLink>
                <AppLink to="/nonprofits" className="er-btn-secondary">
                  Submit another request
                </AppLink>
              </div>
            </article>

            <article className="er-card" id="delivered-report-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">Cited public research</span>
                <span className="er-chip er-chip-human">Person decides use</span>
              </div>
              <h3>Finished public budget report</h3>
              <p className="er-muted">{req.steward_and_delivery.public_report_summary}</p>
              <div className="er-actions er-mt-auto">
                <AppLink to="/help" className="er-btn-secondary">
                  Donate spare tokens on /help
                </AppLink>
                <AppLink to="/fabric" className="er-btn-secondary">
                  Inspect live Tessera queues
                </AppLink>
              </div>
            </article>
          </div>
        </section>
      )}
    </div>
  );
}
