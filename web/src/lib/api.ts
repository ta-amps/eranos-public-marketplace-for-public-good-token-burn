import { SNAPSHOT_DATA } from "virtual:snapshot-data";

import { SNAPSHOT } from "../config";
import { findBannedWords } from "./copy";
import {
  OPEN_SPDX_ALLOWLIST,
  allSkills,
  allTools,
  type CatalogResponse,
  type KitDraft,
  type PracticeVerifyResponse,
  type PublishedKit,
  type TracksResponse,
} from "./types";

export type ApiPath =
  | "/api/catalog"
  | `/api/catalog?${string}`
  | `/api/catalog/${string}`
  | "/api/tracks"
  | "/api/examples"
  | "/api/requests"
  | "/api/fabric"
  | "/api/open-tasks"
  | `/api/nouns/${string}`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function snapshotKey(path: string): string {
  return path.replace(/^\/api\//, "");
}

function isQuarantinedEntry(entry: PublishedKit): boolean {
  if (entry.visibility_scope === "surface_only" || entry.kit?.visibility_scope === "surface_only") {
    return true;
  }
  const tags = [...(entry.tags ?? []), ...(entry.kit?.tags ?? [])].map((t) => t.toLowerCase());
  return tags.includes("status:quarantined");
}

function filterCatalogSnapshot(raw: CatalogResponse, search: string): CatalogResponse {
  const params = new URLSearchParams(search);
  const wantDomain = (params.get("domain") ?? "").trim();
  const wantTrack = (params.get("track") ?? "").trim();
  const wantTag = (params.get("tag") ?? "").trim().toLowerCase();
  const wantCohort = (params.get("cohort") ?? "").trim().toLowerCase();
  const wantSpdx = (params.get("spdx") ?? "").trim().toLowerCase();
  const wantQ = (params.get("q") ?? "").trim().toLowerCase();

  const kits = (raw.kits ?? []).filter((entry) => {
    if (isQuarantinedEntry(entry)) return false;
    const kit = entry.kit;
    if (wantDomain && kit.domain !== wantDomain) return false;
    if (wantTrack && kit.track_id !== wantTrack) return false;
    if (wantTag) {
      const mergedTags = new Set(
        [...(entry.tags ?? []), ...(kit.tags ?? [])].map((t) => t.toLowerCase()),
      );
      if (!mergedTags.has(wantTag)) return false;
    }
    const rawCohorts =
      entry.target_cohorts?.length
        ? entry.target_cohorts
        : kit.target_cohorts?.length
          ? kit.target_cohorts
          : ["all"];
    const mergedCohorts = new Set(rawCohorts.map((c) => c.toLowerCase()));
    if (!wantCohort) {
      if (!mergedCohorts.has("all")) return false;
    } else if (!mergedCohorts.has("all") && !mergedCohorts.has(wantCohort)) {
      return false;
    }
    if (wantSpdx) {
      const spdx = (entry.spdx_license || kit.spdx_license || "Apache-2.0").toLowerCase();
      if (spdx !== wantSpdx) return false;
    }
    if (wantQ) {
      const hay = [
        kit.kit_id,
        kit.title,
        kit.summary,
        kit.target_org,
        kit.track_id,
        kit.domain,
        ...(entry.tags ?? []),
        ...(kit.tags ?? []),
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(wantQ)) return false;
    }
    return true;
  });

  return {
    ...raw,
    kits,
  };
}

export async function getJson<T>(path: ApiPath, signal?: AbortSignal): Promise<T> {
  if (SNAPSHOT) {
    if (path === "/api/catalog" || path.startsWith("/api/catalog?")) {
      const base = SNAPSHOT_DATA["catalog"] as CatalogResponse | undefined;
      if (!base) {
        throw new ApiError(`The snapshot has no data for /api/catalog. Run make snapshot.`);
      }
      const qIndex = path.indexOf("?");
      const search = qIndex >= 0 ? path.slice(qIndex + 1) : "";
      return filterCatalogSnapshot(base, search) as unknown as T;
    }
    const key = snapshotKey(path);
    if (!(key in SNAPSHOT_DATA)) {
      throw new ApiError(`The snapshot has no data for ${path}. Run make snapshot.`, 404);
    }
    const found = SNAPSHOT_DATA[key];
    if (path.startsWith("/api/catalog/") && found && isQuarantinedEntry(found as PublishedKit)) {
      throw new ApiError(`${path} is quarantined and not in the public catalog.`, 404);
    }
    return found as T;
  }
  const response = await fetch(path, { headers: { accept: "application/json" }, signal });
  if (!response.ok) {
    throw new ApiError(`${path} answered ${response.status} ${response.statusText}`, response.status);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new ApiError(`${path} returned unexpected content-type ${contentType || "unknown"}`, 502);
  }
  return (await response.json()) as T;
}

const STRICT_HUMAN_ONLY_KINDS = new Set([
  "interview",
  "legal_judgment",
  "crisis_safety_plan",
  "individual_decision",
  "external_send",
]);

async function sha256Hex(input: string): Promise<string> {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function runSnapshotPracticeVerify(
  draft: KitDraft,
  explicitTrackId?: string,
): Promise<PracticeVerifyResponse> {
  const checksRun = [
    "schema_and_copy_boundaries",
    "spdx_open_license",
    "track_exists",
  ];
  const issues: string[] = [];
  const spdx = (draft.spdx_license || "Apache-2.0").trim();
  const trackId = (explicitTrackId ?? draft.track_id ?? "").trim() || null;

  if (!(OPEN_SPDX_ALLOWLIST as readonly string[]).includes(spdx)) {
    issues.push(
      `spdx_license '${spdx}' is not in open-license allowlist: ${OPEN_SPDX_ALLOWLIST.join(", ")}`,
    );
  }

  const allText = [
    draft.title,
    draft.summary,
    draft.target_org,
    ...draft.steps.map((s) => `${s.title} ${s.guidance}`),
    ...draft.checklist,
    ...draft.fixtures.map((f) => `${f.scenario} ${f.sample_input}`),
  ].join(" ");
  const banned = findBannedWords(allText);
  if (banned.length > 0) {
    issues.push(`non-accusatory copy check failed (${banned.join(", ")})`);
  }

  for (const step of draft.steps) {
    if (STRICT_HUMAN_ONLY_KINDS.has(step.kind) && step.boundary !== "human_only") {
      issues.push(`step '${step.id}' of kind '${step.kind}' must stay human_only`);
    }
  }
  const humanSteps = draft.steps.filter((s) => s.boundary === "human_only").map((s) => s.id);
  if (humanSteps.length === 0) {
    issues.push("at least one workflow step must have boundary='human_only'");
  }

  const tracksData = SNAPSHOT_DATA["tracks"] as TracksResponse | undefined;
  const track = tracksData?.tracks?.find((t) => t.id === trackId);
  if (!track) {
    issues.push(`unknown track_id: ${trackId ?? ""}`);
  } else {
    checksRun.push("track_domain_match", "track_allowed_artifacts", "track_required_human_only");
    if (draft.domain !== track.domain) {
      issues.push(`kit domain '${draft.domain}' does not match track domain '${track.domain}'`);
    }
    const stepKinds = new Set(draft.steps.filter((s) => s.boundary === "human_only").map((s) => s.kind));
    for (const reqKind of track.required_human_only) {
      if (!stepKinds.has(reqKind)) {
        issues.push(`missing required human_only step of kind '${reqKind}' for track '${track.id}'`);
      }
    }
  }

  const tools = allTools(draft);
  const skills = allSkills(draft);
  checksRun.push(
    "mcp_tool_json_schema",
    "source_citations_https",
    "example_fixtures_escalation_coverage",
  );
  for (const tl of tools) {
    if (!tl.read_only) {
      issues.push(`MCP tool '${tl.name}' must be read_only`);
    }
    if (tl.input_schema?.type !== "object") {
      issues.push(`MCP tool '${tl.name}' input_schema.type must be 'object'`);
    }
  }
  for (const sk of skills) {
    if (!sk.refuses || sk.refuses.length === 0) {
      issues.push(`Agent skill '${sk.name}' must declare at least one refusal`);
    }
  }
  for (const src of draft.sources) {
    if (!src.url.startsWith("https://")) {
      issues.push(`source '${src.title}' must use https://`);
    }
  }
  for (const fx of draft.fixtures) {
    if (![fx.sample_input, fx.scenario].some((text) => text.includes("Practice case:") || text.includes("SYNTHETIC"))) {
      issues.push(`fixture '${fx.id}' must carry the practice-case mark`);
    }
  }
  if (!draft.fixtures.some((fx) => fx.expected_human_escalation)) {
    issues.push("at least one example test must expect expected_human_escalation=true");
  }

  const passed = issues.length === 0;
  const canonical = JSON.stringify({
    checks_run: checksRun,
    issues,
    kit_id: draft.kit_id,
    passed,
    spdx_license: spdx,
    track_id: trackId,
  });
  const receiptSha256 = await sha256Hex(canonical);

  return {
    is_example: true,
    passed,
    persisted: false,
    kit_id: draft.kit_id,
    track_id: trackId,
    spdx_license: spdx,
    checks_run: checksRun,
    issues,
    fixture_count: draft.fixtures.length,
    human_only_steps: humanSteps,
    receipt_sha256: receiptSha256,
    receipt_scope: "validation_outcome",
    artifact_bound: false,
  };
}

export async function runPracticeVerify(
  draft: KitDraft,
  trackId?: string,
): Promise<PracticeVerifyResponse> {
  if (SNAPSHOT) {
    return runSnapshotPracticeVerify(draft, trackId);
  }
  const response = await fetch("/api/practice", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      draft,
      track_id: trackId ?? draft.track_id,
    }),
  });
  if (!response.ok) {
    throw new ApiError(`/api/practice answered ${response.status} ${response.statusText}`, response.status);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new ApiError(`/api/practice returned unexpected content-type ${contentType || "unknown"}`, 502);
  }
  return (await response.json()) as PracticeVerifyResponse;
}
