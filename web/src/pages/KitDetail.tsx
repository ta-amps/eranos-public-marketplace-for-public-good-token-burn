import { useState } from "react";

import { BoundaryBadge, DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import { runPracticeVerify } from "../lib/api";
import {
  allSkills,
  allTools,
  type PracticeVerifyResponse,
  type PublishedKit,
} from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

export function KitDetail({ id }: { id: string }) {
  const { state, reload } = useResource<PublishedKit>(`/api/catalog/${encodeURIComponent(id)}`);
  const [practiceState, setPracticeState] = useState<
    | { status: "idle" }
    | { status: "running" }
    | { status: "ready"; result: PracticeVerifyResponse }
    | { status: "error"; message: string }
  >({ status: "idle" });

  if (state.status === "loading") {
    return <p className="er-muted">Loading kit {id}...</p>;
  }
  if (state.status === "error") {
    return (
      <section className="er-card">
        <h1>Kit unavailable</h1>
        <ErrorAlert
          title={`Could not load ${id}`}
          message={state.message}
          onRetry={state.httpStatus === 400 || state.httpStatus === 404 ? undefined : reload}
        />
        <p>
          <AppLink to="/catalog">Back to catalog</AppLink>
        </p>
      </section>
    );
  }

  const entry = state.data;
  const { kit, verification } = entry;
  const skills = allSkills(kit);
  const tools = allTools(kit);
  const spdxLicense = entry.spdx_license || kit.spdx_license || "Apache-2.0";
  const visibilityScope = entry.visibility_scope || kit.visibility_scope || "public_commons";
  const cohorts = entry.target_cohorts?.length
    ? entry.target_cohorts
    : kit.target_cohorts?.length
      ? kit.target_cohorts
      : ["all"];
  const tags = Array.from(new Set([...(entry.tags ?? []), ...(kit.tags ?? [])]));

  const handlePracticeRun = () => {
    setPracticeState({ status: "running" });
    runPracticeVerify(kit, kit.track_id)
      .then((result) => setPracticeState({ status: "ready", result }))
      .catch((err: unknown) =>
        setPracticeState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  };

  return (
    <div>
      <p className="er-muted er-mb-12" >
        <AppLink to="/catalog">Back to the kit catalog</AppLink> / <code>{kit.kit_id}</code>
      </p>

      <section className="er-hero">
        <div className="er-chip-row er-mb-12" >
          <span className="er-chip er-chip-neutral">{kit.kit_id}</span>
          <DomainBadge domain={kit.domain} />
          <span className="er-chip er-chip-assists">{kit.deliverable_kind.replace(/_/g, " ")}</span>
          <span className="er-chip er-chip-neutral">SPDX: {spdxLicense}</span>
          <span className="er-chip er-chip-drafts">Scope: {visibilityScope}</span>
          {entry.steward_signoff && (
            <span className="er-chip er-chip-steward">Steward sign-off: {entry.steward_signoff}</span>
          )}
        </div>
        <h1>{kit.title}</h1>
        <p className="er-lede">{kit.summary}</p>
        <p className="er-muted">
          <strong>Target organization:</strong> {kit.target_org} · <strong>Track:</strong>{" "}
          <code>{kit.track_id}</code> · <strong>Catalog version:</strong> v{entry.catalog_version} ·{" "}
          <strong>Cohorts:</strong> <code>{cohorts.join(", ")}</code>
        </p>
        {tags.length > 0 && (
          <div className="er-chip-row er-mt-10" >
            {tags.map((t) => (
              <span key={t} className="er-chip er-chip-neutral">
                {t}
              </span>
            ))}
          </div>
        )}
      </section>

      <section className="er-section">
        <div className="er-practice-panel">
          <div className="er-chip-row">
            <span className="er-chip er-chip-drafts">Practice check: nothing is saved</span>
            <code>persisted: false</code>
          </div>
          <h2>Run the practice check yourself</h2>
          <p className="er-muted">
            Run the kit&apos;s deterministic checks again, in memory, with nothing saved: the step boundaries, the
            open license, the wording rules, the source links and the <code>SYNTHETIC</code> test cases.
          </p>
          <div className="er-actions">
            <button
              type="button"
              className="er-btn-primary"
              data-testid="run-practice-verifier"
              disabled={practiceState.status === "running"}
              onClick={handlePracticeRun}
            >
              {practiceState.status === "running"
                ? "Running the practice check..."
                : "Run the practice check"}
            </button>
          </div>
          {practiceState.status === "error" && (
            <ErrorAlert
              title="Practice verification failed"
              message={practiceState.message}
              onRetry={handlePracticeRun}
            />
          )}
          {practiceState.status === "ready" && (
            <div data-testid="practice-verifier-result">
              <div className="er-chip-row er-mb-10" >
                <span
                  className={
                    practiceState.result.passed ? "er-chip er-chip-drafts" : "er-chip er-chip-human"
                  }
                >
                  {practiceState.result.passed ? "PASSED" : "FAILED"}
                </span>
                <span className="er-chip er-chip-neutral">
                  persisted: {String(practiceState.result.persisted)}
                </span>
                <span className="er-chip er-chip-neutral">
                  SPDX: {practiceState.result.spdx_license}
                </span>
              </div>
              <dl className="er-dl">
                <div>
                  <dt>Validation outcome SHA-256 (does not bind draft content)</dt>
                  <dd>{practiceState.result.receipt_sha256}</dd>
                </div>
                <div>
                  <dt>Persisted to storage</dt>
                  <dd>{String(practiceState.result.persisted)}</dd>
                </div>
                <div>
                  <dt>Checks executed</dt>
                  <dd>{practiceState.result.checks_run.join(", ")}</dd>
                </div>
                <div>
                  <dt>Issues found</dt>
                  <dd>
                    {practiceState.result.issues.length === 0
                      ? "0 issues"
                      : practiceState.result.issues.join("; ")}
                  </dd>
                </div>
              </dl>
            </div>
          )}
        </div>
      </section>

      <section className="er-section">
        <h2>Step map: what the agent prepares and what stays with a person</h2>
        <ul className="er-step-list">
          {kit.steps.map((step) => (
            <li key={step.id} className="er-step-item">
              <div className="er-chip-row er-mb-6" >
                <BoundaryBadge boundary={step.boundary} />
                <strong>{step.title}</strong>
                <span className="er-chip er-chip-neutral">{step.kind}</span>
                <span className="er-muted">Actor: {step.actor}</span>
              </div>
              <p className="er-muted">{step.guidance}</p>
            </li>
          ))}
        </ul>
      </section>

      {(skills.length > 0 || tools.length > 0 || kit.artifacts.length > 0) && (
        <div className="er-grid">
          {skills.map((sk) => (
            <section key={sk.name} className="er-card">
              <div className="er-chip-row">
                <BoundaryBadge boundary={sk.boundary} />
                <code>SKILL</code>
              </div>
              <h2>Skill · {sk.name}</h2>
              <p className="er-muted">{sk.description}</p>
              <p className="er-muted">
                <strong>Instructions:</strong> {sk.instructions}
              </p>
              <div>
                <strong>Explicitly refuses:</strong>
                <ul>
                  {sk.refuses.map((r) => (
                    <li key={r} className="er-muted">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ))}

          {tools.map((tl) => (
            <section key={tl.name} className="er-card">
              <div className="er-chip-row">
                <span className="er-chip er-chip-assists">Read-only connection (MCP)</span>
                <code>{tl.name}</code>
              </div>
              <h2>Connection · {tl.name}</h2>
              <p className="er-muted">{tl.description}</p>
              <p className="er-muted">
                <strong>Output fields:</strong> <code>{tl.output_fields.join(", ")}</code>
              </p>
              <pre className="er-code" tabIndex={0}>{JSON.stringify(tl.input_schema, null, 2)}</pre>
            </section>
          ))}

          {kit.artifacts.map((art) => (
            <section key={art.name} className="er-card">
              <div className="er-chip-row">
                <BoundaryBadge boundary={art.boundary} />
                <span className="er-chip er-chip-neutral">{art.artifact_format}</span>
              </div>
              <h2>{art.title}</h2>
              <p className="er-muted">{art.summary}</p>
              <pre className="er-code" tabIndex={0}>{JSON.stringify(art.spec, null, 2)}</pre>
            </section>
          ))}
        </div>
      )}

      <div className="er-grid">
        <section className="er-card">
          <h2>Checklist for staff</h2>
          <ul>
            {kit.checklist.map((item) => (
              <li key={item} className="er-muted">
                {item}
              </li>
            ))}
          </ul>
          <h3>Public sources</h3>
          <ul>
            {kit.sources.map((src) => (
              <li key={src.url} className="er-muted">
                <a href={src.url} target="_blank" rel="noreferrer">
                  {src.title}
                </a>{" "}
                (checked {src.checked_date})
              </li>
            ))}
          </ul>
        </section>

        <section className="er-card">
          <h2>Synthetic test cases ({verification.fixture_count})</h2>
          {kit.fixtures.map((fx) => (
            <div key={fx.id}  className="er-fixture-divider">
              <div className="er-chip-row">
                <code>{fx.id}</code>
                <span className={fx.expected_human_escalation ? "er-chip er-chip-human" : "er-chip er-chip-drafts"}>
                  {fx.expected_human_escalation ? "Escalates to person" : "Routine prep"}
                </span>
              </div>
              <p className="er-muted">
                <strong>{fx.scenario}:</strong> {fx.sample_input}
              </p>
            </div>
          ))}
        </section>
      </div>

      <section className="er-section">
        <h2>Review receipts: the builder is not the reviewer (drafter != reviewer)</h2>
        <dl className="er-dl">
          <div>
            <dt>Drafted on eq02 by</dt>
            <dd>
              {kit.drafted_by} ({kit.drafted_by_key})
            </dd>
          </div>
          <div>
            <dt>Independently reviewed on eq03 by</dt>
            <dd>
              {entry.reviewed_by} ({entry.reviewed_by_key})
            </dd>
          </div>
          <div>
            <dt>Content-addressed blob SHA-256</dt>
            <dd>{entry.blob_sha256 ?? "--"}</dd>
          </div>
          <div>
            <dt>eq02 draft receipt</dt>
            <dd>{entry.draft_receipt ?? "--"}</dd>
          </div>
          <div>
            <dt>eq03 review receipt</dt>
            <dd>{entry.review_receipt ?? "--"}</dd>
          </div>
          <div>
            <dt>Reviewer notes</dt>
            <dd>{entry.review_notes}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
