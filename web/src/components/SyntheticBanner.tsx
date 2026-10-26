import { SNAPSHOT } from "../config";

export function SyntheticBanner() {
  return (
    <div className="er-banner" data-testid="synthetic-banner" role="region" aria-label="Synthetic data notice">
      <span>
        SYNTHETIC FIXTURES ONLY · Two-step verified volunteer agent kits (drafter ≠ reviewer); people keep all interviews &amp; decisions.
      </span>
      <span>{SNAPSHOT ? "Offline snapshot mode" : "Live API mode"}</span>
    </div>
  );
}
