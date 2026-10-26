import type { AutonomyBoundary, TrackDomain } from "../lib/types";

export function BoundaryBadge({ boundary }: { boundary: AutonomyBoundary }) {
  if (boundary === "drafts") {
    return <span className="er-chip er-chip-drafts">Agent drafts</span>;
  }
  if (boundary === "assists") {
    return <span className="er-chip er-chip-assists">Agent assists</span>;
  }
  return <span className="er-chip er-chip-human">Human only</span>;
}

export function DomainBadge({ domain }: { domain: TrackDomain }) {
  if (domain === "anti_exploitation") {
    return <span className="er-chip er-chip-steward">Anti-exploitation NGO</span>;
  }
  return <span className="er-chip er-chip-neutral">Nonprofit operations</span>;
}
