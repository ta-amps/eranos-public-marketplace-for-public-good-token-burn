import { useState } from "react";

import type { HelpNoun } from "../lib/nouns";
import { ErrorAlert } from "./ErrorAlert";

/** The contributor's path, rendered from the `eranos.instructions/help` noun as given. */
export function OnboardingSteps({ noun, error, onRetry }: { noun: HelpNoun | null; error?: string; onRetry: () => void }) {
  const [status, setStatus] = useState("");

  if (error) return <ErrorAlert title="Steps unavailable" message={error} onRetry={onRetry} />;
  if (!noun) return <p className="er-muted">Loading the steps...</p>;

  async function copyCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command);
      setStatus(noun?.ui.copied ?? "");
    } catch {
      setStatus(noun?.ui.copy_failed ?? "");
    }
  }

  return (
    <div data-testid="onboarding-steps">
      <h3>{noun.title}</h3>
      <p className="er-muted er-measure">{noun.summary}</p>
      <div className="er-command">
        <code data-testid="one-command">{noun.command}</code>
        <button type="button" className="er-btn-secondary" onClick={() => void copyCommand(noun.command)}>
          {noun.ui.copy}
        </button>
        <span className="er-small" role="status" aria-live="polite">
          {status}
        </span>
      </div>
      <p className="er-small er-measure">{noun.command_note}</p>
      <ol className="er-plain-steps" data-testid="onboarding-step-list">
        {noun.steps.map((step) => (
          <li key={step.id}>
            <strong>{step.title}.</strong> {step.detail}
            {step.example && <code className="er-small er-step-example">{step.example}</code>}
          </li>
        ))}
      </ol>
    </div>
  );
}
