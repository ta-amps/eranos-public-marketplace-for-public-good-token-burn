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

export function DomainBadge({ domain, label }: { domain: TrackDomain; label?: string | null }) {
  if (domain === "anti_exploitation") {
    return <span className="er-chip er-chip-steward">{label || "Anti-exploitation NGO"}</span>;
  }
  if (domain === "nonprofit_ops") {
    return <span className="er-chip er-chip-neutral">{label || "Nonprofit operations"}</span>;
  }
  const formatted = label || domain.replace(/_/g, " ");
  return <span className="er-chip er-chip-assists">{formatted}</span>;
}
