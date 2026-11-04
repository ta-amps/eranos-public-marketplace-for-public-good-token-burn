import { useMemo, useState } from "react";

import { BoundaryBadge, DomainBadge } from "../components/BoundaryBadge";
import { ErrorAlert } from "../components/ErrorAlert";
import type { ApiPath } from "../lib/api";
import {
  OPEN_SPDX_ALLOWLIST,
  allSkills,
  allTools,
  type CatalogResponse,
  type TracksResponse,
} from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";

function formatDomainLabel(dom: string): string {
  if (dom === "anti_exploitation") return "Anti-exploitation NGO";
  if (dom === "nonprofit_ops") return "Nonprofit operations";
  return dom.replace(/_/g, " ");
}

export function Catalog() {
  const [domain, setDomain] = useState<string>("");
  const [track, setTrack] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [cohort, setCohort] = useState<string>("");
  const [spdx, setSpdx] = useState<string>("");
  const [q, setQ] = useState<string>("");

  const baseCatalog = useResource<CatalogResponse>("/api/catalog?view=page");
  const tracksRes = useResource<TracksResponse>("/api/tracks");

  const catalogPath: ApiPath = useMemo<ApiPath>(() => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (track) params.set("track", track);
    if (tag) params.set("tag", tag);
    if (cohort) params.set("cohort", cohort);
    if (spdx) params.set("spdx", spdx);
    if (q.trim()) params.set("q", q.trim());
    const qs = params.toString();
    return qs ? (`/api/catalog?${qs}&view=page` as const) : "/api/catalog?view=page";
  }, [domain, track, tag, cohort, spdx, q]);

  const filteredCatalog = useResource<CatalogResponse>(catalogPath);
  const activeState = catalogPath === "/api/catalog?view=page" ? baseCatalog.state : filteredCatalog.state;
  const activeReload = () => {
    baseCatalog.reload();
    if (catalogPath !== "/api/catalog?view=page") {
      filteredCatalog.reload();
    }
  };

  const baseKits = baseCatalog.state.status === "ready" ? baseCatalog.state.data.kits : [];

  const domains = useMemo(
    () => Array.from(new Set(baseKits.map((k) => k.kit.domain))).sort(),
    [baseKits],
  );

  const trackOptions = useMemo(() => {
    if (tracksRes.state.status === "ready") {
      return tracksRes.state.data.tracks.map((t) => ({ id: t.id, title: t.title }));
    }
    return Array.from(new Set(baseKits.map((k) => k.kit.track_id)))
      .sort()
      .map((id) => ({ id, title: id }));
  }, [tracksRes.state, baseKits]);

  const tags = useMemo(() => {
    const out = new Set<string>();
    for (const entry of baseKits) {
      for (const t of [...(entry.tags ?? []), ...(entry.kit.tags ?? [])].filter((tag) => !/^(status|reuse|request|package):/.test(tag))) {
        if (t && !t.startsWith("status:")) out.add(t);
      }
    }
    return Array.from(out).sort();
  }, [baseKits]);

  const cohorts = useMemo(() => {
    const out = new Set<string>(["ngo_hotline", "ngo_legal_aid", "nonprofit_ops"]);
    for (const entry of baseKits) {
      for (const c of [...(entry.target_cohorts ?? []), ...(entry.kit.target_cohorts ?? [])]) {
        if (c && c !== "all") out.add(c);
      }
    }
    return Array.from(out).sort();
  }, [baseKits]);

  const hasActiveFilters = Boolean(domain || track || tag || cohort || spdx || q.trim());

  const resetFilters = () => {
    setDomain("");
    setTrack("");
    setTag("");
    setCohort("");
    setSpdx("");
    setQ("");
  };

  const kits = activeState.status === "ready" ? activeState.data.kits : [];

  return (
    <div>
      <section className="er-section">
        <h1>Kit catalog: reviewed agent kits</h1>
        <p className="er-lede">
          Every kit here passed its checks and tests on <code>eq02</code>, then a review by a different worker
          on <code>eq03</code> (<code>drafter != reviewer</code>), before it was published to{" "}
          <code>eranos.catalog</code>. All of them use example data. A reviewed kit is not certified for your
          organization.
        </p>

        <div className="er-filter-bar" role="group" aria-label="Quick category filter buttons">
          <button
            type="button"
            className="er-filter-btn"
            aria-pressed={domain === ""}
            onClick={() => setDomain("")}
          >
            All domains
          </button>
          {domains.map((dom) => (
            <button
              key={dom}
              type="button"
              className="er-filter-btn"
              aria-pressed={domain === dom}
              onClick={() => setDomain(dom)}
            >
              {formatDomainLabel(dom)}
            </button>
          ))}
        </div>

        <div className="er-filter-panel" aria-label="Catalog governance and discovery filters">
          <div className="er-filter-grid">
            <div className="er-field">
              <label htmlFor="filter-domain">Domain</label>
              <select
                id="filter-domain"
                className="er-select"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              >
                <option value="">All domains</option>
                {domains.map((dom) => (
                  <option key={dom} value={dom}>
                    {formatDomainLabel(dom)}
                  </option>
                ))}
              </select>
            </div>

            <div className="er-field">
              <label htmlFor="filter-track">Track</label>
              <select
                id="filter-track"
                className="er-select"
                value={track}
                onChange={(e) => setTrack(e.target.value)}
              >
                <option value="">All tracks</option>
                {trackOptions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id}
                  </option>
                ))}
              </select>
            </div>

            <div className="er-field">
              <label htmlFor="filter-tag">Tag</label>
              <select
                id="filter-tag"
                className="er-select"
                value={tag}
                onChange={(e) => setTag(e.target.value)}
              >
                <option value="">All tags</option>
                {tags.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <div className="er-field">
              <label htmlFor="filter-cohort">Cohort</label>
              <select
                id="filter-cohort"
                className="er-select"
                value={cohort}
                onChange={(e) => setCohort(e.target.value)}
              >
                <option value="">Universal default (all)</option>
                {cohorts.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <div className="er-field">
              <label htmlFor="filter-spdx">SPDX License</label>
              <select
                id="filter-spdx"
                className="er-select"
                value={spdx}
                onChange={(e) => setSpdx(e.target.value)}
              >
                <option value="">All open licenses</option>
                {OPEN_SPDX_ALLOWLIST.map((lic) => (
                  <option key={lic} value={lic}>
                    {lic}
                  </option>
                ))}
              </select>
            </div>

            <div className="er-field">
              <label htmlFor="filter-q">Search kits</label>
              <input
                id="filter-q"
                type="search"
                className="er-input"
                placeholder="Title, org, tag, ID..."
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
          </div>

          {hasActiveFilters && (
            <div className="er-actions er-mt-12" >
              <button type="button" className="er-btn-secondary" onClick={resetFilters}>
                Reset filters
              </button>
            </div>
          )}
        </div>

        {activeState.status === "loading" && <p className="er-muted">Loading kits...</p>}
        {activeState.status === "error" && (
          <ErrorAlert
            title="Error loading catalog"
            message={activeState.message}
            onRetry={activeReload}
          />
        )}
        {activeState.status === "ready" && kits.length === 0 && (
          <div className="er-empty-state" data-testid="catalog-empty-state">
            <p className="er-muted">
              <strong>No kits match the selected filters.</strong>
            </p>
            <button type="button" className="er-btn-secondary" onClick={resetFilters}>
              Reset filters
            </button>
          </div>
        )}
        {activeState.status === "ready" && kits.length > 0 && (
          <div className="er-grid">
            {kits.map((entry) => {
              const humanCount = entry.kit.steps.filter((s) => s.boundary === "human_only").length;
              const skills = allSkills(entry.kit);
              const tools = allTools(entry.kit);
              const primaryBoundary = skills[0]?.boundary ?? entry.kit.artifacts[0]?.boundary ?? "assists";
              const kitSpdx = entry.spdx_license || entry.kit.spdx_license || "Apache-2.0";
              const kitCohorts = entry.target_cohorts?.length
                ? entry.target_cohorts
                : entry.kit.target_cohorts?.length
                  ? entry.kit.target_cohorts
                  : ["all"];
              return (
                <article key={entry.kit.kit_id} className="er-card">
                  <div className="er-chip-row">
                    <span className="er-chip er-chip-neutral">{entry.kit.kit_id}</span>
                    <DomainBadge domain={entry.kit.domain} />
                    <BoundaryBadge boundary={primaryBoundary} />
                    <span className="er-chip er-chip-neutral">SPDX: {kitSpdx}</span>
                  </div>
                  <h2>
                    <AppLink to={`/catalog/${entry.kit.kit_id}`}>{entry.kit.title}</AppLink>
                  </h2>
                  <p className="er-muted" data-source-text>{entry.kit.summary}</p>
                  <p className="er-muted">
                    <strong>Organization:</strong> {entry.kit.target_org} · <strong>Kind:</strong>{" "}
                    <code>{entry.kit.deliverable_kind}</code>
                  </p>
                  <p className="er-muted">
                    <strong>Cohorts:</strong> <code>{kitCohorts.join(", ")}</code>
                  </p>
                  <p className="er-muted">
                    <strong>Step map:</strong> {entry.kit.steps.length} steps, {humanCount} person only ·{" "}
                    {skills.length} skill(s) · {tools.length} connection(s) · {entry.kit.artifacts.length} file(s)
                  </p>
                  <div className="er-actions er-mt-auto" >
                    <AppLink to={`/catalog/${entry.kit.kit_id}`} className="er-btn-secondary">
                      Open the kit
                    </AppLink>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
