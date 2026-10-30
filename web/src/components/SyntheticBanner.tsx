import { SNAPSHOT } from "../config";

export function SyntheticBanner() {
  return (
    <div className="er-banner" data-testid="synthetic-banner" role="region" aria-label="Synthetic data notice">
      <span>
        SYNTHETIC DATA ONLY · A different volunteer reviews every kit · People keep every interview and decision
      </span>
      <span>{SNAPSHOT ? "Offline snapshot mode" : "Live API mode"}</span>
    </div>
  );
}
