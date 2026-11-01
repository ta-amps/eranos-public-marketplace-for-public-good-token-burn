import { agentStartAsset } from "./agent_start.js";
import kitSchema from "./kit-draft.schema.json" with { type: "json" };
import { schemaIssues } from "./schema.js";
import { accessResponse, accessDescriptor, CORS_HEADERS, publicFeedPayload } from "./access.js";
// Cloudflare Cloud Worker for Eranos. Serves the web app's static files (SPA fallback), intercepts
// AI-agent discovery endpoints (/favicon.svg, /healthz, /robots.txt, /llms.txt, /llms-full.txt,
// /.well-known/agent-card.json, POST /mcp) before SPA fallback, and serves /api/* natively 24/7 from
// Cloudflare D1 (ta-amps-fabric) + env.TESSERA Service Binding, with optional Fly.io origin fallback.
// An address outside the app's pages answers 404 with the app's "Page not found" view, and /connect is the
// app's own page, with its text rendered in for readers that run no script.

const DEFAULT_API_ORIGIN = "https://eranos-api.fly.dev";
const ERANOS_VERSION = "0.1.0";
const KIT_ID_RE = /^[A-Z]{2,4}-[A-Z0-9]{2,8}-[0-9]{2}$/;
const OPEN_SPDX_ALLOWLIST = new Set(["Apache-2.0", "MIT", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0"]);
const HUMAN_ONLY_KINDS = new Set([
  "interview",
  "crisis_safety_plan",
  "legal_judgment",
  "individual_decision",
  "case_referral",
  "grant_signoff",
  "external_send",
]);
const BANNED_ACCUSATIONS_RE =
  /\b(criminal|criminals|trafficker|traffickers|scammer|scammers|fraudster|fraudsters|guilty|acting illegally)\b/gi;
const PROHIBITED_TOPICS_RE =
  /\b(csam|child sexual|grooming kit|sextortion sample|intimate-image sample|revenge porn|self-harm guide|track real person location)\b/gi;

const PRACTICE_CHECKS = [
  "track_alignment",
  "human_only_boundaries",
  "example_fixtures",
  "non_accusatory_copy",
  "prohibited_topics",
  "spdx_license_allowlist",
  "cited_sources",
  "deliverable_alignment",
];

const SUPPORTED_MCP_PROTOCOLS = new Set(["2024-11-05", "2025-03-26", "2025-06-18"]);

const ERANOS_QUEUE_LABELS = [
  ["eq01", "Scope"],
  ["eq02", "Draft + verify"],
  ["eq03", "Independent review"],
];
const ZERO_QUEUE_COUNTS = {
  ready: 0,
  leased: 0,
  waiting: 0,
  done: 0,
  dead: 0,
  cancelled: 0,
};

// The tile mark (Paper & Ink). The ink tile turns paper in a dark browser theme.
const FAVICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><style>.i{fill:#11161F}@media (prefers-color-scheme:dark){.i{fill:#F5F2EA}}</style><rect x="0" y="0" width="44" height="44" rx="10" fill="#2A5DB0"/><rect x="56" y="0" width="44" height="44" rx="10" fill="#B8541F"/><rect class="i" x="0" y="56" width="44" height="44" rx="10"/><rect x="56" y="56" width="44" height="44" rx="10" fill="#2A5DB0"/></svg>`;

const ROBOTS_TXT = `User-agent: *
Allow: /
Allow: /api/catalog
Allow: /api/tracks
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /agent.md
Allow: /.well-known/agent-card.json
Allow: /.well-known/agent.json
Allow: /.well-known/security.txt
`;

const SECURITY_TXT = `Contact: https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/security/advisories
Expires: 2027-10-31T23:59:59.000Z
Preferred-Languages: en
Canonical: https://eranos.ta-amps.workers.dev/.well-known/security.txt
Policy: https://eranos.ta-amps.workers.dev/report
`;

const FALLBACK_LLMS_TXT = `# Eranos: spare tokens for good

> A two-sided marketplace. People donate AI capacity they won't use; their agents build, check and independently review agent kits for nonprofits, NGOs and public-good groups (eq01 check -> eq02 build -> eq03 review -> eranos.catalog). An agent kit is a seed pack of nouns and verbs made for one organization's agent. Tessera is the shared infrastructure underneath; Agora (https://agora.ta-amps.workers.dev/) explains how it all works.

## The two sides
- /help: I want to help. Connect your own agent, copy a starting brief and see the open tasks.
- /nonprofits: My NGO needs help. Ask for information or a reusable process, in plain words, with no private information.

## Discovery & API
- /connect: public tools and tracked Tessera anonymous/keyed access; /connect.json is the machine-readable twin.
- /api/catalog: Verified two-step reviewed NGO kits (?domain=&track=&tag=&cohort=&spdx=&q=)
- /api/tracks: Public-good NGO and nonprofit build tracks
- /api/examples: Example needs in organizations' own words, and the count of recorded example runs
- /api/practice: POST zero-storage deterministic practice verifier (persisted: false)
- /mcp: Stateless JSON-RPC 2.0 MCP endpoint (list_tracks, search_catalog, get_kit, practice_verify_kit)
- /privacy, /terms, /report, /.well-known/security.txt: Privacy, terms of use, problem reporting and RFC 9116 security contact
- /.well-known/agent-card.json: Machine-readable agent capability card
`;

const FALLBACK_LLMS_FULL_TXT = `${FALLBACK_LLMS_TXT}
## Core Invariants
- Example fixtures only (each carries the practice-case mark; zero real PII).
- Interviews, crisis safety planning, legal judgments, individual decisions, and external sends stay strictly human_only.
- Atomic two-step publication: drafter != reviewer across both worker ID and Tessera key ID, plus parker != resumer on steward sign-off.
- Open SPDX allowlist: Apache-2.0, MIT, BSD-3-Clause, CC-BY-4.0, CC0-1.0.
`;

const FALLBACK_TRACKS = [
  {
    id: "coerced-work-hotline-routing",
    title: "Coerced Recruitment & Crisis Helpline Routing Kits",
    domain: "anti_exploitation",
    summary:
      "Builds verified multi-jurisdiction helpline directories and safe-intake triage scripts for NGOs, keeping all crisis planning strictly human-only.",
    sister_area: "recruitment",
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "helpline_directory_schema", "synthetic_test_pack"],
    required_human_only: ["interview", "crisis_safety_plan", "external_send"],
    never: ["Give automated safety or exit advice directly to a person in danger"],
    sources: [],
  },
  {
    id: "grant-and-compliance-ops",
    title: "Small-Nonprofit Grant Reporting & Restricted-Fund Kits",
    domain: "nonprofit_ops",
    summary:
      "Gives small nonprofits deterministic budget-reconciliation checks, restricted-grant deadline trackers, and audit-prep checklists.",
    sister_area: null,
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "compliance_checklist", "synthetic_test_pack"],
    required_human_only: ["individual_decision", "external_send"],
    never: ["Submit regulatory filings externally without treasurer sign-off"],
    sources: [],
  },
  {
    id: "housing-and-charity-verification",
    title: "Rental Deposit & Disaster-Relief Charity Check Kits",
    domain: "anti_exploitation",
    summary:
      "Provides community legal-aid clinics and disaster-response coalitions with public-registry lookup schemas and deposit-escrow checklists.",
    sister_area: "charity",
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "verification_checklist", "synthetic_test_pack"],
    required_human_only: ["individual_decision", "external_send"],
    never: ["File regulator complaints automatically without human sign-off"],
    sources: [],
  },
  {
    id: "intake-and-referral-triage",
    title: "Multilingual Service-Finder & Warm-Referral Operations",
    domain: "nonprofit_ops",
    summary:
      "Helps community nonprofits match published program rules to intake notes and draft warm-referral summaries while keeping eligibility decisions human-only.",
    sister_area: null,
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "referral_handoff_template", "synthetic_test_pack"],
    required_human_only: ["interview", "individual_decision"],
    never: ["Allow an agent to deny service eligibility on its own"],
    sources: [],
  },
  {
    id: "job-recruitment-triage",
    title: "Cross-Border Job Offer & Fee-Shift Intake Kits",
    domain: "anti_exploitation",
    summary:
      "Equips migrant-worker centres and labour-rights clinics with fee arithmetic checks, contract comparison checklists, and escalation workflows.",
    sister_area: "recruitment",
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "intake_checklist", "synthetic_test_pack"],
    required_human_only: ["interview", "individual_decision"],
    never: ["Allow an agent to decide a worker's legal claim or conduct a client interview"],
    sources: [],
  },
  {
    id: "volunteer-shift-and-sop-builder",
    title: "Field Volunteer Onboarding & Incident Escalation SOPs",
    domain: "nonprofit_ops",
    summary:
      "Equips mutual-aid kitchens, mobile clinics, and disaster-relief teams with role-card builders, shift handoff checklists, and human-escalation trees.",
    sister_area: null,
    organizations: [],
    allowed_artifacts: ["agent_skill", "mcp_tool_spec", "shift_sop_checklist", "synthetic_test_pack"],
    required_human_only: ["crisis_safety_plan", "individual_decision"],
    never: ["Replace human incident commanders or medical leads with automated triage"],
    sources: [],
  },
];

const FALLBACK_STAGES = [
  {
    queue: "eq01",
    node: "spec",
    title: "Scope & safety gate",
    effect_class: "read",
    purpose: "Check track alignment, required human_only steps, and safe-topic rules before drafting.",
  },
  {
    queue: "eq02",
    node: "draft",
    title: "Volunteer agent draft & deterministic checks",
    effect_class: "write-internal",
    purpose: "One volunteer agent builds the kit, fixtures, skill, and MCP tool spec; verifier runs.",
  },
  {
    queue: "eq03",
    node: "review",
    title: "Independent review & CAS catalog publish",
    effect_class: "write-internal",
    purpose: "A different agent or human steward (drafter != reviewer) audits and publishes to eranos.catalog.",
  },
];

const MCP_TOOLS = [
  {
    name: "list_tracks",
    description: "List all public-good NGO and nonprofit build tracks and required human_only boundaries.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true },
  },
  {
    name: "search_catalog",
    description:
      "Search and filter two-step verified NGO kits by domain, track, tag, cohort, open SPDX license, or free-text query.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string" },
        track: { type: "string" },
        tag: { type: "string" },
        cohort: { type: "string" },
        spdx: { type: "string" },
        q: { type: "string" },
      },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
  },
  {
    name: "get_kit",
    description:
      "Fetch a single verified PublishedKit bundle including skills, read-only MCP tool schemas, checklists, fixtures, and receipts.",
    inputSchema: {
      type: "object",
      required: ["kit_id"],
      properties: { kit_id: { type: "string" }, cohort: { type: "string" } },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
  },
  {
    name: "practice_verify_kit",
    description:
      "Zero-storage deterministic verifier (persisted: false) for boundaries, copy, SPDX and SYNTHETIC fixtures. Receipt scope is validation_outcome; it does not bind draft content or publish a kit.",
    inputSchema: {
      type: "object",
      required: ["draft"],
      properties: {
        draft: { type: "object" },
        track_id: { type: "string" },
      },
      additionalProperties: true,
    },
    annotations: { readOnlyHint: true },
  },
].map((tool) => ({...tool, description: "Public tool; no API key required. " + tool.description}));

const HOP_BY_HOP = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

// connect-src names Tessera: the request box signs a nonprofit up and files its request there.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self' https://tessera.ta-amps.workers.dev",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const SECURITY_HEADERS = {
  "strict-transport-security": "max-age=31536000; includeSubDomains",
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=()",
  "x-frame-options": "DENY",
  "content-security-policy": CONTENT_SECURITY_POLICY,
};

function stripHopByHop(headers) {
  const listed = (headers.get("connection") || "")
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
  for (const name of [...HOP_BY_HOP, ...listed]) headers.delete(name);
}

function finish(response, method) {
  const out = new Response(method === "HEAD" ? null : response.body, response);
  stripHopByHop(out.headers);
  for (const [name, value] of Object.entries({...SECURITY_HEADERS, ...CORS_HEADERS})) out.headers.set(name, value);
  out.headers.set("x-request-id", crypto.randomUUID());
  if (method !== "GET" && method !== "HEAD") out.headers.set("cache-control", "no-store");
  return out;
}

// Owner, October 31: "DO NOT INCLUDE SYNTHETIC." Everything this Worker answers says "example" instead, uses general
// names ("tests", "evaluations") for checks, and marks a practice case "Practice case: an example, not a real person
// or case." Stored records and the verifier may still hold the former internal mark: visibleWords() translates on
// the way out, internalWords() on the way in, so the two agree. eranos/visible.py holds the same rules for the
// snapshot files.
const CASE_MARK = "Practice case: an example, not a real person or case.";
const VISIBLE_RULES = [
  [/SYNTHETIC:\s*/g, `${CASE_MARK} `],
  [/\bSYNTHETIC\b/g, "practice-case"],
  [/synthetic_example/g, "example"],
  [/synthetic_/g, "example_"],
  [/_synthetic\b/g, "_example"],
  [/\bSynthetic (examples?)\b/g, (_, word) => word.charAt(0).toUpperCase() + word.slice(1)],
  [/\bsynthetic (examples?)\b/g, "$1"],
  [/Synthetic/g, "Example"],
  [/synthetic/gi, "example"],
];
function visibleText(text) {
  let out = String(text);
  for (const [pattern, replacement] of VISIBLE_RULES) out = out.replace(pattern, replacement);
  return out;
}
// Never rewritten: a quote, a source's own text or a request's own words stay verbatim, and a record bound by a
// digest (any *_sha256 field) is served exactly as stored, so quotes are never misquoted and digests still verify.
// Such records carry the word only until their producers stop writing it (the B1 workers drop those claims).
const VERBATIM_KEYS = new Set(["quote", "quotes", "excerpt", "source_text", "text"]);
function visibleWords(value) {
  if (typeof value === "string") return visibleText(value);
  if (Array.isArray(value)) return value.map(visibleWords);
  if (value && typeof value === "object") {
    if (Object.keys(value).some((key) => key.endsWith("_sha256"))) return value;
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      out[key.toLowerCase() === "synthetic" ? "is_example" : visibleText(key)] = VERBATIM_KEYS.has(key) ? item : visibleWords(item);
    }
    return out;
  }
  return value;
}
// The names an agent sends back, in the verifier's words (only the marks and the identifiers the verifier reads).
const INTERNAL_KEYS = { is_example: "synthetic", example_fixtures: "synthetic_fixtures", example_only: "synthetic_only" };
const INTERNAL_VALUES = { example_test_pack: "synthetic_test_pack", example_fixtures: "synthetic_fixtures" };
function internalWords(value) {
  if (typeof value === "string") {
    if (Object.prototype.hasOwnProperty.call(INTERNAL_VALUES, value)) return INTERNAL_VALUES[value];
    return value.split(`${CASE_MARK} `).join("SYNTHETIC: ").split(CASE_MARK).join("SYNTHETIC:").replace(/\bpractice-case\b/g, "SYNTHETIC");
  }
  if (Array.isArray(value)) return value.map(internalWords);
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, item] of Object.entries(value)) out[INTERNAL_KEYS[key] || key] = internalWords(item);
    return out;
  }
  return value;
}

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(visibleWords(data)), {
    status,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}

function textResp(rawText, mediaType = "text/plain; charset=utf-8", status = 200) {
  const text = visibleText(rawText);
  return new Response(text, {
    status,
    headers: { "content-type": mediaType, "cache-control": "public, max-age=300" },
  });
}

function problem(status, title, detail, code = "invalid_request", extraHeaders = {}) {
  return new Response(JSON.stringify(visibleWords({ type: "about:blank", title, status, detail, code })), {
    status,
    headers: { "content-type": "application/problem+json", "cache-control": "no-store", ...extraHeaders },
  });
}

// A D1 fault (an unreachable or uninitialised mirror) falls back to the snapshot exported with this deploy, the
// same as a missing record, instead of answering 500.
async function getHeadRecord(db, store, key) {
  if (!db) return null;
  try {
    return await readHeadRecord(db, store, key);
  } catch {
    return null;
  }
}

async function readHeadRecord(db, store, key) {
  const row = await db
    .prepare(
      "SELECT r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.key = ? AND h.namespace = 'main' AND r.namespace = h.namespace AND h.producer_surface = 'surface:eranos' AND r.producer_surface = h.producer_surface AND h.visibility_scope = 'public_commons' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:quarantined') AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') AND (h.store != 'eranos.catalog' OR EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:verified'))"
    )
    .bind(store, key)
    .first();
  return row ? JSON.parse(row.value) : null;
}

// Null when the mirror faults, so the caller can fall back to the snapshot; an empty list is a real answer.
async function listHeadRecords(db, store) {
  if (!db) return [];
  try {
    return await readHeadRecords(db, store);
  } catch {
    return null;
  }
}

async function readHeadRecords(db, store) {
  const res = await db
    .prepare(
      "SELECT r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.namespace = 'main' AND r.namespace = h.namespace AND h.producer_surface = 'surface:eranos' AND r.producer_surface = h.producer_surface AND h.visibility_scope = 'public_commons' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:quarantined') AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') AND (h.store != 'eranos.catalog' OR EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:verified')) ORDER BY h.key"
    )
    .bind(store)
    .all();
  return (res.results || []).map((r) => JSON.parse(r.value));
}

async function fetchAssetJson(request, env, assetPath) {
  if (!env || !env.ASSETS) return null;
  try {
    const resp = await env.ASSETS.fetch(new Request(new URL(assetPath, request.url), { method: "GET" }));
    const ct = (resp.headers.get("content-type") || "").toLowerCase();
    if (!resp.ok || ct.includes("text/html")) {
      await resp.body?.cancel();
      return null;
    }
    return await resp.json();
  } catch {
    return null;
  }
}

async function fetchAssetText(request, env, assetPath) {
  if (!env || !env.ASSETS) return null;
  try {
    const resp = await env.ASSETS.fetch(new Request(new URL(assetPath, request.url), { method: "GET" }));
    const ct = (resp.headers.get("content-type") || "").toLowerCase();
    if (!resp.ok || ct.includes("text/html")) {
      await resp.body?.cancel();
      return null;
    }
    const text = await resp.text();
    if (text.trimStart().toLowerCase().startsWith("<!doctype html")) return null;
    return text;
  } catch {
    return null;
  }
}

async function loadTracksPayload(request, env) {
  // Tracks are repository data, so the snapshot built with this deploy is the source of truth.
  // The stored record is only a fallback, so an older stored copy can never outlive a new build.
  const snap = await fetchAssetJson(request, env, "/snapshot/tracks.json");
  let baseTracks = snap && Array.isArray(snap.tracks) ? snap.tracks : null;
  if (!baseTracks) {
    const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "tracks");
    baseTracks = stored && Array.isArray(stored.tracks) ? stored.tracks : FALLBACK_TRACKS;
  }
  const liveKits = filterCatalogKits(await loadRawCatalogList(request, env), new URLSearchParams());
  const byTrack = new Map();
  for (const entry of liveKits) {
    const kit = entry && entry.kit && typeof entry.kit === "object" ? entry.kit : {};
    const tid = String(kit.track_id || "").trim();
    const kid = String(kit.kit_id || "").trim();
    if (!tid || !kid) continue;
    if (!byTrack.has(tid)) byTrack.set(tid, []);
    const arr = byTrack.get(tid);
    if (!arr.includes(kid)) arr.push(kid);
  }
  const tracks = baseTracks.map((track) => {
    const ids = (byTrack.get(track.id) || []).slice().sort();
    return {
      ...track,
      catalog_kit_ids: ids,
      kit_ready: ids.length > 0,
      process_ready: Boolean(track.process_class ?? track.process_ready),
    };
  });
  return { synthetic: true, tracks };
}

async function loadRequestsPayload(request, env) {
  const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "requests");
  if (stored && Array.isArray(stored.requests)) return stored;
  const snap = await fetchAssetJson(request, env, "/snapshot/requests.json");
  if (snap && Array.isArray(snap.requests)) return snap;
  return { synthetic: true, stages: FALLBACK_STAGES, requests: [] };
}

async function loadRawCatalogList(request, env) {
  if (env && env.FABRIC_DB) {
    const fromDb = await listHeadRecords(env.FABRIC_DB, "eranos.catalog");
    if (fromDb !== null) return fromDb;
  }
  const snap = await fetchAssetJson(request, env, "/snapshot/catalog.json");
  if (snap && Array.isArray(snap.kits)) return snap.kits;
  return [];
}

function isQuarantinedRecord(entry) {
  if (!entry || typeof entry !== "object") return true;
  const kit = entry.kit && typeof entry.kit === "object" ? entry.kit : {};
  if (entry.visibility_scope !== "public_commons" || (kit.visibility_scope && kit.visibility_scope !== "public_commons")) return true;
  const allTags = [
    ...(Array.isArray(entry.tags) ? entry.tags : []),
    ...(Array.isArray(kit.tags) ? kit.tags : []),
  ];
  return !allTags.includes("status:verified") || allTags.some((t) => String(t).trim().toLowerCase() === "status:quarantined");
}

function filterCatalogKits(entries, searchParams) {
  const domQ = (searchParams.get("domain") || "").trim().toLowerCase();
  const trackQ = (searchParams.get("track") || "").trim().toLowerCase();
  const tagRaw = (searchParams.get("tag") || "").trim();
  const tagParts = tagRaw
    ? tagRaw
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
    : [];
  const cohortQ = (searchParams.get("cohort") || "").trim().toLowerCase();
  const spdxQ = (searchParams.get("spdx") || "").trim().toLowerCase();
  const textQ = (searchParams.get("q") || "").trim().toLowerCase();

  const out = [];
  for (const entry of entries) {
    if (isQuarantinedRecord(entry)) continue;
    const kit = entry.kit && typeof entry.kit === "object" ? entry.kit : {};
    const allTags = Array.from(
      new Set([
        ...(Array.isArray(entry.tags) ? entry.tags : []),
        ...(Array.isArray(kit.tags) ? kit.tags : []),
      ])
    ).map((t) => String(t));
    const lowerTags = new Set(allTags.map((t) => t.toLowerCase()));

    const rawCohorts = Array.isArray(entry.target_cohorts)
      ? entry.target_cohorts
      : Array.isArray(kit.target_cohorts)
        ? kit.target_cohorts
        : ["all"];
    const cohorts = rawCohorts.map((c) => String(c).toLowerCase());

    if (!cohortQ) {
      if (!cohorts.includes("all")) continue;
    } else {
      const bare = cohortQ.startsWith("cohort:") ? cohortQ.slice(7) : cohortQ;
      if (
        !(
          cohorts.includes("all") ||
          cohorts.includes(cohortQ) ||
          cohorts.includes(bare) ||
          cohorts.includes(`cohort:${bare}`)
        )
      ) {
        continue;
      }
    }

    if (domQ && String(kit.domain || "").toLowerCase() !== domQ) continue;
    if (trackQ && String(kit.track_id || "").toLowerCase() !== trackQ) continue;
    if (tagParts.length > 0 && !tagParts.every((tp) => lowerTags.has(tp))) continue;

    const kitSpdx = String(entry.spdx_license || kit.spdx_license || "Apache-2.0").toLowerCase();
    if (spdxQ && kitSpdx !== spdxQ) continue;

    if (textQ) {
      const skills = [
        ...(kit.skill ? [kit.skill] : []),
        ...(Array.isArray(kit.skills) ? kit.skills : []),
      ];
      const tools = [...(kit.tool ? [kit.tool] : []), ...(Array.isArray(kit.tools) ? kit.tools : [])];
      const artifacts = Array.isArray(kit.artifacts) ? kit.artifacts : [];
      const haystack = [
        kit.kit_id,
        kit.title,
        kit.summary,
        kit.target_org,
        kit.track_id,
        kit.domain,
        kit.deliverable_kind,
        entry.spdx_license || kit.spdx_license,
        ...allTags,
        ...cohorts,
        ...skills.flatMap((s) => [s?.name, s?.description]),
        ...tools.flatMap((t) => [t?.name, t?.description]),
        ...artifacts.flatMap((a) => [a?.name, a?.title, a?.summary]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(textQ)) continue;
    }

    out.push(entry);
  }
  return out;
}

function collectStrings(node, acc = []) {
  if (typeof node === "string") {
    acc.push(node);
  } else if (Array.isArray(node)) {
    for (const item of node) collectStrings(item, acc);
  } else if (node && typeof node === "object") {
    for (const val of Object.values(node)) collectStrings(val, acc);
  }
  return acc;
}

function canonicalJson(val) {
  if (val === null || typeof val !== "object") return JSON.stringify(val);
  if (Array.isArray(val)) return `[${val.map((item) => canonicalJson(item)).join(",")}]`;
  const keys = Object.keys(val).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(val[k])}`).join(",")}}`;
}

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function unwrapDraftPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const govKeys = [
    "spdx_license",
    "tags",
    "target_cohorts",
    "producer_surface",
    "visibility_scope",
    "allowed_surfaces",
  ];
  if (payload.draft && typeof payload.draft === "object" && !Array.isArray(payload.draft)) {
    const raw = { ...payload.draft };
    if (payload.request && typeof payload.request === "object") {
      for (const k of govKeys) {
        if (!(k in raw) && k in payload.request) raw[k] = payload.request[k];
      }
    }
    return raw;
  }
  if (payload.kit && typeof payload.kit === "object" && !Array.isArray(payload.kit)) {
    const raw = { ...payload.kit };
    for (const k of govKeys) {
      if (!(k in raw) && k in payload) raw[k] = payload[k];
    }
    return raw;
  }
  return { ...payload };
}

// The digest a build submission carries: SHA-256 of the draft as canonical JSON (same as the API).
async function withDraftDigest(result, body) {
  const draft = body && typeof body.draft === "object" && body.draft !== null && !Array.isArray(body.draft) ? body.draft : body;
  return { ...result, draft_sha256: await sha256Hex(canonicalJson(draft)) };
}

// The web app's pages, as web/src/router.tsx lists them (tests/test_marketplace_site.py keeps the two equal).
// Any other page address gets the app shell, whose router shows "Page not found", with status 404, so agents
// and link checkers can tell a missing page from a real one.
const APP_PAGES = ["/", "/help", "/nonprofits", "/catalog", "/contribute", "/tracks", "/fabric", "/about", "/connect", "/library", "/requests", "/privacy", "/terms", "/report"];
const APP_KIT_PAGE_RE = /^\/catalog\/[^/]+$/;
// A request's status page and its result page (the private link's key stays in the #k= fragment, which never
// reaches this Worker).
const APP_REQUEST_PAGE_RE = /^\/requests\/[^/]+(?:\/result)?$/;
// Example request addresses: these show the example request (instructions/request-example), never a real record.
// REQ-INTAKE-07 is the address an earlier film used; it now opens the same example, and the page says so.
const EXAMPLE_REQUEST_ALIASES = { example: "request-example", "example-process": "request-example-process", "REQ-INTAKE-07": "request-example" };

function isAppPage(pathname) {
  const path = pathname.replace(/\/+$/, "") || "/";
  return APP_PAGES.includes(path) || APP_KIT_PAGE_RE.test(path) || APP_REQUEST_PAGE_RE.test(path);
}

// A path segment, percent-decoded, or BROKEN_ESCAPE when it holds a broken escape such as "%E0%A4%A". Before,
// decodeURIComponent threw there, and the Worker answered Cloudflare's bare 500 page with no CORS headers.
const BROKEN_ESCAPE = Symbol("broken percent escape");

function decodeSegment(raw) {
  try {
    return decodeURIComponent(raw);
  } catch {
    return BROKEN_ESCAPE;
  }
}

// A kit page whose id is malformed or names no kit in the catalog still gets the app shell, whose "Kit
// unavailable" view explains, but with status 404, so agents and link checkers can tell a wrong kit link from a
// real one. The lookup is the one /api/catalog/<id> makes for the page itself.
async function isMissingKitPage(request, env, pathname) {
  const path = pathname.replace(/\/+$/, "");
  if (!APP_KIT_PAGE_RE.test(path)) return false;
  const kitId = decodeSegment(path.slice("/catalog/".length));
  if (kitId === BROKEN_ESCAPE || !KIT_ID_RE.test(kitId)) return true;
  const plain = new Request(new URL(`/api/catalog/${encodeURIComponent(kitId)}`, request.url));
  return !(await lookupSingleKit(plain, env, kitId));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// /connect in the site's own layout: the app shell, titled from the `eranos.instructions/connect` noun, with that
// noun's text in its page for readers that run no script. The app then renders the same noun with the site's
// navigation, skip link and light and dark themes. /connect.json, the machine-readable access modes, is unchanged.
async function connectPage(request, env) {
  const found = await loadNoun(request, env, "eranos.instructions", "connect");
  const noun = found && found.value && typeof found.value === "object" ? found.value : {};
  const descriptor = accessDescriptor("eranos");
  const links = noun.links || {};
  const tessera = links.fabric_connect || descriptor.fabric_connect_url;
  const title = noun.title || "Connect to Eranos";
  const lines = [
    `<h1>${escapeHtml(title)}</h1>`,
    `<p>${escapeHtml(noun.authentication || descriptor.authentication)}</p>`,
    `<p>${escapeHtml(noun.restrictions || descriptor.restrictions)}</p>`,
    noun.anonymous_link ? `<p><a href="${escapeHtml(tessera)}">${escapeHtml(noun.anonymous_link)}</a></p>` : "",
    noun.key_link ? `<p><a href="${escapeHtml(tessera)}">${escapeHtml(noun.key_link)}</a></p>` : "",
    noun.anonymous_note ? `<p>${escapeHtml(noun.anonymous_note)}</p>` : "",
    noun.bearer_note ? `<p>${escapeHtml(noun.bearer_note)}</p>` : "",
    `<p><a href="${escapeHtml(links.machine || "/connect.json")}">${escapeHtml(noun.machine_link || "Machine-readable access modes")}</a></p>`,
  ];
  const main = `<main id="main">${lines.join("")}</main>`;
  const page = /<main\b[^>]*>[\s\S]*?<\/main>/;
  let html = null;
  if (env && env.ASSETS) {
    try {
      const shell = await env.ASSETS.fetch(new Request(new URL("/", request.url), { method: "GET" }));
      if (shell.ok && (shell.headers.get("content-type") || "").includes("text/html")) html = await shell.text();
    } catch {
      html = null;
    }
  }
  if (html && page.test(html)) {
    html = html.replace(/<title>[^<]*<\/title>/, () => `<title>${escapeHtml(title)}</title>`).replace(page, () => main);
  } else {
    html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title><body>${main}</body></html>`;
  }
  return new Response(request.method === "HEAD" ? null : visibleText(html), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

// Every public version of a request or plan record, oldest first. The volunteer worker writes each state change of
// a request as a new version of eranos.requests/<id> that cites its receipt, so this history is the status page's
// event source. Null when the mirror faults or holds no public version.
const HISTORY_STORES = new Set(["eranos.requests", "eranos.plans"]);

async function readRecordHistory(db, store, key) {
  if (!db) return null;
  try {
    const res = await db
      .prepare(
        "SELECT r.version AS version, r.created_at AS created_at, r.value AS value FROM records r JOIN record_heads h ON h.namespace = r.namespace AND h.store = r.store AND h.key = r.key WHERE r.store = ? AND r.key = ? AND r.namespace = 'main' AND r.producer_surface = 'surface:eranos' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') ORDER BY r.version"
      )
      .bind(store, key)
      .all();
    const versions = (res.results || []).map((r) => ({ version: Number(r.version), created_at: Number(r.created_at), value: JSON.parse(r.value) }));
    return versions.length ? versions : null;
  } catch {
    return null;
  }
}

// Public noun reads are cached at the edge for 10 s, so many viewers polling one request page cost one D1 read
// each 10 s instead of one each. Outside a Cloudflare runtime there is no cache and the read runs every time.
const NOUN_CACHE_SECONDS = 10;

async function edgeCached(request, compute) {
  const cache = typeof caches !== "undefined" && caches.default ? caches.default : null;
  if (!cache || request.method !== "GET") return compute();
  const key = new Request(new URL(request.url).toString(), { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;
  const response = await compute();
  if (response.status !== 200 || response.headers.get("x-skip-edge-cache") === "1") {
    response.headers.delete("x-skip-edge-cache");
    return response;
  }
  const fresh = new Response(response.body, response);
  fresh.headers.set("cache-control", `public, max-age=${NOUN_CACHE_SECONDS}`);
  await cache.put(key, fresh.clone());
  return fresh;
}

// The open verbs a volunteer's agent can claim, read with this surface's own key: only what an open brief already
// shows (its title, kind and the request and part it serves), never outputs, keys or attempts.
const OPEN_TASK_QUEUES = ["eq02", "eq03"];

function openTaskView(verb, queue) {
  const brief = verb && typeof verb.brief === "object" && verb.brief ? verb.brief : {};
  const tags = Array.isArray(verb.tags) ? verb.tags : [];
  return {
    task_id: String(verb.task_id || ""),
    queue,
    kind: String(verb.kind || ""),
    title: String(brief.title || brief.goal || "").slice(0, 140),
    request_id: brief.request_id ? String(brief.request_id) : null,
    part: Number.isInteger(brief.part) ? brief.part : null,
    created_at: Number(verb.created_at) || null,
    open_to_anonymous: tags.includes("open:anonymous"),
  };
}

// Public Eranos nouns (page text, plans, requests, delivered reports, sources, verb templates):
// Tessera's mirror first, live Coordinator fallback for dynamic request/plan/solution stores when the D1 mirror lags,
// then the snapshot exported from Tessera with this deploy.
const PUBLIC_NOUN_STORES = new Set(["eranos.instructions", "eranos.plans", "eranos.requests", "eranos.solutions", "eranos.sources", "eranos.verb_templates"]);
const LIVE_COORDINATOR_STORES = new Set(["eranos.requests", "eranos.plans", "eranos.solutions"]);
const NOUN_KEY_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const LIVE_REQUEST_ID_RE = /^rq-r_[0-9a-f]{32}-[0-9a-z]+$/;
const SHORT_BADGE_RE = /^R-[A-Z0-9]{4}$/i;

async function fetchCoordinatorPublicRecord(env, store, key) {
  if (!env || !env.TESSERA || !env.TESSERA_SURFACE_KEY || !LIVE_COORDINATOR_STORES.has(store)) return null;
  try {
    const resp = await env.TESSERA.fetch(
      `https://tessera.ta-amps.workers.dev/ns/main/v1/stores/${encodeURIComponent(store)}/records/${encodeURIComponent(key)}`,
      { headers: { Authorization: `Bearer ${env.TESSERA_SURFACE_KEY}`, "X-Surface-Id": "eranos" } }
    );
    if (!resp.ok) {
      await resp.body?.cancel();
      return null;
    }
    const rec = await resp.json();
    if (!rec || typeof rec !== "object") return null;
    if (rec.producer_surface !== "surface:eranos" || rec.visibility_scope !== "public_commons") return null;
    const tags = Array.isArray(rec.tags) ? rec.tags : [];
    if (tags.some((t) => String(t).trim().toLowerCase() === "status:quarantined")) return null;
    if (rec.value === null || rec.value === undefined) return null;
    return { synthetic: true, store, key, version: Number(rec.version) || 1, value: rec.value };
  } catch {
    return null;
  }
}

async function fetchPendingRequestVerb(env, reqId) {
  if (!env || !env.TESSERA || !env.TESSERA_SURFACE_KEY || !LIVE_REQUEST_ID_RE.test(reqId)) return null;
  try {
    const resp = await env.TESSERA.fetch(
      `https://tessera.ta-amps.workers.dev/ns/main/v1/tasks/${encodeURIComponent(reqId)}`,
      { headers: { Authorization: `Bearer ${env.TESSERA_SURFACE_KEY}`, "X-Surface-Id": "eranos" } }
    );
    if (!resp.ok) {
      await resp.body?.cancel();
      return null;
    }
    const body = await resp.json();
    const task = body && typeof body.task === "object" && body.task ? body.task : body;
    if (!task || typeof task !== "object" || task.queue !== "eq01" || task.kind !== "request") return null;
    const brief = task.brief && typeof task.brief === "object" && task.brief ? task.brief : {};
    const outputType = ["process", "information", "both"].includes(brief.output_type) ? brief.output_type : undefined;
    const frequency = ["one-off", "recurring"].includes(brief.frequency) ? brief.frequency : undefined;
    return {
      task_id: String(task.task_id || reqId),
      state: String(task.state || "ready"),
      created_at: Number(task.created_at) || null,
      ...(outputType ? { output_type: outputType } : {}),
      ...(frequency ? { frequency } : {}),
    };
  } catch {
    return null;
  }
}

async function loadNoun(request, env, store, key) {
  const stored = await getHeadRecord(env.FABRIC_DB, store, key);
  if (stored !== null && stored !== undefined) return { synthetic: true, store, key, value: stored };
  const live = await fetchCoordinatorPublicRecord(env, store, key);
  if (live) return live;
  const snap = await fetchAssetJson(request, env, `/snapshot/nouns/${store}/${key}.json`);
  return snap && snap.store === store && snap.key === key ? snap : null;
}

async function loadNounList(request, env, store) {
  if (env && env.FABRIC_DB) {
    let res = { results: [] };
    try {
      res = await env.FABRIC_DB.prepare(
      "SELECT h.key AS key, h.version AS version, r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.namespace = 'main' AND r.namespace = h.namespace AND h.producer_surface = 'surface:eranos' AND r.producer_surface = h.producer_surface AND h.visibility_scope = 'public_commons' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:quarantined') AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') ORDER BY h.key LIMIT 100"
    ).bind(store).all();
    } catch {
      res = { results: [] };
    }
    const records = (res.results || []).map((r) => ({ key: r.key, version: Number(r.version), value: JSON.parse(r.value) }));
    if (records.length) return { synthetic: true, store, records };
  }
  const snap = await fetchAssetJson(request, env, `/snapshot/nouns/${store}.json`);
  return snap && snap.store === store && Array.isArray(snap.records) ? snap : { synthetic: true, store, records: [] };
}

// /p/<request id>/agent.md and /p/<request id>/practice.md: a process result as Markdown any agent can read. It is
// rendered from the public nouns that hold the result (the example's own noun, or the plan and the solution it
// names), so the page and the agent read the same thing. Nothing is stored and nothing runs here.
const PROCESS_DOC_RE = /^\/p\/([A-Za-z0-9][A-Za-z0-9_.:-]{0,159})\/(agent|practice)\.md$/;
const EXAMPLE_RESULT_NOUNS = { example: "request-example", "example-process": "request-example-process" };

async function loadProcessResult(request, env, id, partNumber) {
  if (Object.prototype.hasOwnProperty.call(EXAMPLE_RESULT_NOUNS, id)) {
    const found = await loadNoun(request, env, "eranos.instructions", EXAMPLE_RESULT_NOUNS[id]);
    const solution = found && found.value && found.value.solution;
    return solution && solution.process ? { process: solution.process, review_receipt: solution.review_receipt || null } : null;
  }
  if (!NOUN_KEY_RE.test(id)) return null;
  const plan = await loadNoun(request, env, "eranos.plans", id);
  const parts = plan && plan.value && Array.isArray(plan.value.parts) ? plan.value.parts : [];
  const part = parts.find((p) => p && p.part === partNumber) || parts.find((p) => p && (p.route === "private-files" || p.route === "process"));
  const resultId = part && (part.kit_id || part.report_id);
  if (!resultId || !NOUN_KEY_RE.test(String(resultId))) return null;
  const solution = await loadNoun(request, env, "eranos.solutions", String(resultId));
  const value = solution && solution.value;
  return value && value.process ? { process: value.process, review_receipt: value.review_receipt || null } : null;
}

// /p/<id>/download: a published process package, read from Tessera with this site's own key (never shown) and
// served as the exact reviewed bytes. Only a catalog record that is published (status:verified, a review receipt)
// and reviewed by a different key than its builder's is served, and the bytes must hash to its blob_sha256.
// <id> is the catalog key (KIT-/PRC-) or a request id whose plan names the part's kit (?part=N).
const PACKAGE_DOWNLOAD_RE = /^\/p\/([A-Za-z0-9][A-Za-z0-9_.:-]{0,159})\/download$/;
const PACKAGE_MAX_BYTES = 25 * 1024 * 1024;
const PACKAGE_RATE = { windowMs: 60_000, max: 10 };
// Best effort, per isolate: a few downloads a minute for each address; the edge cache answers repeats.
const packageHits = new Map();

function packageRateLimited(request) {
  const who = request.headers.get("cf-connecting-ip") || "anonymous";
  const now = Date.now();
  const hit = packageHits.get(who);
  if (!hit || now - hit.start > PACKAGE_RATE.windowMs) {
    if (packageHits.size > 5000) packageHits.clear();
    packageHits.set(who, { start: now, n: 1 });
    return false;
  }
  hit.n += 1;
  return hit.n > PACKAGE_RATE.max;
}

/** Null when the catalog value may be served; otherwise why not. */
function packageRefusal(value) {
  if (!value || typeof value !== "object") return "no such catalog record";
  if (!/^[0-9a-f]{64}$/.test(String(value.blob_sha256 || ""))) return "the record names no package";
  const tags = Array.isArray(value.tags) ? value.tags : [];
  if (tags.includes("status:quarantined") || !tags.includes("status:verified")) return "the package is not published";
  if (!value.review_receipt) return "the package has no review receipt";
  const builder = String(value.drafter_key_id || (value.kit && value.kit.drafted_by_key) || "");
  const reviewer = String(value.reviewer_key_id || value.reviewed_by_key || "");
  if (!builder || !reviewer || builder === reviewer) return "the package was not reviewed by a different key";
  return null;
}

async function packageCatalogKey(request, env, id) {
  if (/^(KIT|PRC)-[A-Z0-9-]{2,60}$/.test(id)) return id;
  if (!NOUN_KEY_RE.test(id) || Object.prototype.hasOwnProperty.call(EXAMPLE_REQUEST_ALIASES, id)) return null;
  const part = Number(new URL(request.url).searchParams.get("part")) || null;
  const plan = await getHeadRecord(env.FABRIC_DB, "eranos.plans", id);
  const parts = plan && Array.isArray(plan.parts) ? plan.parts : [];
  const found = parts.find((p) => p && (part ? p.part === part : (p.route === "private-files" || p.route === "process") && p.kit_id));
  return found && found.kit_id && /^(KIT|PRC)-[A-Z0-9-]{2,60}$/.test(String(found.kit_id)) ? String(found.kit_id) : null;
}

/** The published package record for <id>, or null; read from the live mirror only (snapshot examples have none). */
async function publishedPackage(request, env, id) {
  const key = await packageCatalogKey(request, env, id);
  const value = key ? await getHeadRecord(env.FABRIC_DB, "eranos.catalog", key) : null;
  return key && value && !packageRefusal(value) ? { key, value } : null;
}

async function readCapped(response, max) {
  const declared = Number(response.headers.get("content-length") || "0");
  if (declared > max) return null;
  const reader = response.body ? response.body.getReader() : null;
  if (!reader) return new Uint8Array(await response.arrayBuffer());
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.byteLength;
  }
  return out;
}

async function servePackage(request, env, id) {
  if (packageRateLimited(request)) {
    return problem(429, "Too Many Requests", "Too many downloads from this address; try again in a minute.", "rate_limited", { "retry-after": "60" });
  }
  const key = await packageCatalogKey(request, env, id);
  if (!key) return problem(404, "Not Found", "No process package is published at this address.", "not_found");
  const value = await getHeadRecord(env.FABRIC_DB, "eranos.catalog", key);
  const refusal = packageRefusal(value);
  if (refusal) {
    return problem(value ? 403 : 404, value ? "Forbidden" : "Not Found", `This process package is not served: ${refusal}.`, value ? "not_published" : "not_found");
  }
  if (!env.TESSERA || !env.TESSERA_SURFACE_KEY) {
    return problem(503, "Service Unavailable", "The package store cannot be reached from this site right now.", "unavailable");
  }
  const sha = String(value.blob_sha256);
  const filename = `${key.replace(/[^A-Za-z0-9._-]/g, "")}.tar.gz`;
  const headers = (length) => ({
    "content-type": "application/gzip",
    "content-disposition": `attachment; filename="${filename}"`,
    "x-content-sha256": sha,
    "content-length": String(length),
    "cache-control": "public, max-age=3600",
    "x-content-type-options": "nosniff",
  });
  const edge = typeof caches !== "undefined" ? caches.default : null;
  const cacheKey = new Request(`https://eranos.ta-amps.workers.dev/p/package/${sha}`);
  const hit = edge ? await edge.match(cacheKey) : null;
  if (hit) {
    const bytes = new Uint8Array(await hit.arrayBuffer());
    return new Response(request.method === "HEAD" ? null : bytes, { status: 200, headers: headers(bytes.byteLength) });
  }
  let upstream = null;
  for (const path of [`/v1/blobs/${sha}`, `/ns/main/v1/blobs/${sha}`]) {
    try {
      upstream = await env.TESSERA.fetch(`https://tessera.ta-amps.workers.dev${path}`, {
        headers: { Authorization: `Bearer ${env.TESSERA_SURFACE_KEY}`, "X-Surface-Id": "eranos" },
      });
    } catch {
      upstream = null;
    }
    if (upstream && upstream.status !== 404) break;
  }
  if (!upstream || !upstream.ok) {
    return problem(502, "Bad Gateway", "The package store did not return this package.", "unavailable");
  }
  const bytes = await readCapped(upstream, PACKAGE_MAX_BYTES);
  if (!bytes) return problem(413, "Payload Too Large", "This package is larger than this site serves.", "too_large");
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (digest !== sha) {
    return problem(502, "Bad Gateway", "The stored package did not match its published SHA-256, so it is not served.", "integrity");
  }
  if (edge && request.method === "GET") {
    await edge.put(cacheKey, new Response(bytes, { headers: { "content-type": "application/gzip", "cache-control": "public, max-age=3600" } })).catch(() => undefined);
  }
  return new Response(request.method === "HEAD" ? null : bytes, { status: 200, headers: headers(bytes.byteLength) });
}

// /api/handshake: the public part of Eranos's handshake with Tessera and Herma, never a surface key's grants.
const HANDSHAKE_PUBLIC_FIELDS = ["protocol_version", "surface_id", "surface_version", "clamped_max_chars", "isolated_store_prefix", "backend", "router", "status"];
const HANDSHAKE_RATE = { windowMs: 60_000, max: 10 };
const handshakeHits = new Map();
let negotiationCache = null;

function handshakeRateLimited(request) {
  const who = request.headers.get("cf-connecting-ip") || "anonymous";
  const now = Date.now();
  const hit = handshakeHits.get(who);
  if (!hit || now - hit.start > HANDSHAKE_RATE.windowMs) {
    if (handshakeHits.size > 5000) handshakeHits.clear();
    handshakeHits.set(who, { start: now, n: 1 });
    return false;
  }
  hit.n += 1;
  return hit.n > HANDSHAKE_RATE.max;
}

function publicHandshake(value) {
  if (!value || typeof value !== "object") return null;
  const out = {};
  for (const field of HANDSHAKE_PUBLIC_FIELDS) if (value[field] !== undefined && typeof value[field] !== "object") out[field] = value[field];
  return out;
}

async function cachedNegotiation(env) {
  if (negotiationCache && Date.now() - negotiationCache.at < 300_000) return negotiationCache.value;
  const fallback = {
    is_example: true,
    surface_id: "eranos",
    protocol_version: "1.0",
    backend: "tessera-cloud",
    isolated_store_prefix: "eranos.",
    transactional_db_exempt_from_middleware: true,
  };
  const body = JSON.stringify({
    protocol_version: "1.0",
    surface_id: "eranos",
    surface_version: ERANOS_VERSION,
    requested_max_chars: 4000,
    requested_queues: ["eq01", "eq02", "eq03"],
    requested_stores: ["eranos.catalog", "eranos.index", "eranos.meta"],
  });
  const ask = async (binding, url, key) => {
    if (!binding) return null;
    try {
      const headers = { "Content-Type": "application/json", "X-Surface-Id": "eranos" };
      if (key) headers.Authorization = `Bearer ${key}`;
      const resp = await binding.fetch(url, { method: "POST", headers, body });
      if (!resp.ok) {
        await resp.body?.cancel();
        return null;
      }
      return publicHandshake(await resp.json());
    } catch {
      return null;
    }
  };
  const tessera = await ask(env.TESSERA, "https://tessera.ta-amps.workers.dev/v1/handshake", env.TESSERA_SURFACE_KEY);
  const herma = env.HERMA_SURFACE_KEY ? await ask(env.HERMA, "https://herma.ta-amps.workers.dev/v1/handshake", env.HERMA_SURFACE_KEY) : null;
  const value = { ...fallback, ...(tessera || {}), ...(tessera ? { tessera } : {}), ...(herma ? { herma } : {}) };
  if (tessera || herma) negotiationCache = { at: Date.now(), value };
  return value;
}

function mdList(items, numbered) {
  return (Array.isArray(items) ? items : []).map((line, i) => `${numbered ? `${i + 1}.` : "-"} ${String(line)}`).join("\n");
}

function processAgentMarkdown(origin, id, found) {
  const o = found.process.task_object || {};
  const t = found.process.task || {};
  return [
    `# ${t.title || o.title || "A reusable process"}`,
    o.description || "",
    "## What you need",
    `- Input: ${t.input || ""}\n- Output: ${t.output || ""}\n- Schedule: ${t.schedule || ""}`,
    "## Set it up",
    mdList(o.install, true),
    "## Run it",
    mdList(o.how_to, true),
    "## Only a person does this",
    mdList(o.person_only, false),
    "## Rules",
    `- Work only on the folder the person chooses. Nothing leaves their computer.\n- Never send anything outside their organization.\n- Before real files, try the made-up examples: ${origin}/p/${id}/practice.md`,
    found.review_receipt ? `Checked by a second volunteer. Review receipt: ${found.review_receipt}` : "",
  ].filter(Boolean).join("\n\n") + "\n";
}

function processPracticeMarkdown(origin, id, found) {
  const cases = Array.isArray(found.process.practice) ? found.process.practice : [];
  if (!cases.length) return null;
  const o = found.process.task_object || {};
  const lines = [
    `# Practice: ${o.title || "a reusable process"}`,
    `Each example is a practice case: an example, not a real person or case. Try the process on them before any real files: ${origin}/p/${id}/agent.md`,
    "Then tell the person what it got right and what it got wrong.",
  ];
  cases.forEach((c, i) => {
    lines.push(`## Example ${i + 1}`, `Input: ${String(c.input || "")}`, `A good result: ${String(c.expect || "")}`);
  });
  return lines.join("\n\n") + "\n";
}

async function practiceVerifyKit(draftPayload, explicitTrackId, tracksById) {
  const raw = unwrapDraftPayload(draftPayload);
  if (!raw) {
    return {
      passed: false,
      persisted: false,
      kit_id: "UNSPECIFIED",
      track_id: "",
      spdx_license: "Apache-2.0",
      issues: ["practice payload must be a JSON object"],
      checks_run: PRACTICE_CHECKS,
      receipt_sha256: await sha256Hex("invalid"),
      receipt_scope: "validation_outcome",
      artifact_bound: false,
    };
  }

  const kitId = String(raw.kit_id || "UNSPECIFIED");
  const spdxLicense = String(raw.spdx_license || "Apache-2.0").trim();
  const payloadTrackId = String(raw.track_id || "").trim();
  const effectiveTrackId = String(explicitTrackId || payloadTrackId).trim();

  const issues = schemaIssues(raw, kitSchema);
  const addIssue = (msg) => {
    if (!issues.includes(msg)) issues.push(msg);
  };

  if (!KIT_ID_RE.test(kitId)) {
    addIssue(`kit_id '${kitId}' must match pattern ^[A-Z]{2,4}-[A-Z0-9]{2,8}-[0-9]{2}$`);
  }

  if (!OPEN_SPDX_ALLOWLIST.has(spdxLicense)) {
    addIssue(
      `spdx_license '${spdxLicense}' must be in open SPDX allowlist (${Array.from(OPEN_SPDX_ALLOWLIST).sort().join(", ")})`
    );
  }

  if (raw.visibility_scope === "allowlist_surfaces" && (!Array.isArray(raw.allowed_surfaces) || !raw.allowed_surfaces.length)) addIssue("allowlist_surfaces requires allowed_surfaces");
  if (Array.isArray(raw.target_cohorts) && (!raw.target_cohorts.length || raw.target_cohorts.some((c) => !/^[a-z0-9][a-z0-9_:-]{1,63}$/.test(String(c).trim().toLowerCase())))) addIssue("invalid target_cohorts");
  if (raw.producer_surface && !/^surface:[a-z0-9][a-z0-9_-]{1,39}$/.test(raw.producer_surface)) addIssue("invalid producer_surface");
  if (Array.isArray(raw.allowed_surfaces) && raw.allowed_surfaces.some((s) => !/^surface:[a-z0-9][a-z0-9_-]{1,39}$/.test(s))) addIssue("invalid allowed_surfaces");
  if (Array.isArray(raw.tags) && raw.tags.some((t) => !/^[a-z0-9][a-z0-9_.-]{0,31}:[A-Za-z0-9][A-Za-z0-9_./-]{0,63}$/.test(String(t).trim()))) addIssue("invalid tags");
  const allStrings = collectStrings(raw);
  const badWords = new Set();
  const badTopics = new Set();
  for (const str of allStrings) {
    for (const m of str.matchAll(BANNED_ACCUSATIONS_RE)) badWords.add(m[0].toLowerCase());
    for (const m of str.matchAll(PROHIBITED_TOPICS_RE)) badTopics.add(m[0].toLowerCase());
  }
  if (badWords.size > 0) {
    addIssue(`non-accusatory copy rule violated: ${Array.from(badWords).sort().join(", ")}`);
  }
  if (badTopics.size > 0) {
    addIssue(`prohibited collection topic refused: ${Array.from(badTopics).sort().join(", ")}`);
  }

  const steps = raw.steps;
  if (!Array.isArray(steps) || steps.length < 2) {
    addIssue("steps must be a list of at least 2 workflow steps");
  } else {
    let hasHumanOnly = false;
    for (let i = 0; i < steps.length; i += 1) {
      const s = steps[i];
      if (!s || typeof s !== "object") {
        addIssue(`step[${i}] must be an object`);
        continue;
      }
      const sid = String(s.id || `step_${i}`);
      const skind = String(s.kind || "");
      const sbound = String(s.boundary || "");
      if (sbound !== "drafts" && sbound !== "assists" && sbound !== "human_only") {
        addIssue(`step '${sid}' boundary must be 'drafts', 'assists', or 'human_only' (got '${sbound}')`);
      }
      if (sbound === "human_only") hasHumanOnly = true;
      if (HUMAN_ONLY_KINDS.has(skind) && sbound !== "human_only") {
        addIssue(`step '${sid}' of kind '${skind}' must keep boundary='human_only'`);
      }
    }
    if (!hasHumanOnly) addIssue("every kit must declare at least one human_only workflow step");
  }

  const fixtures = raw.fixtures;
  if (!Array.isArray(fixtures) || fixtures.length < 2) {
    addIssue("fixtures must provide at least 2 synthetic test cases");
  } else {
    let hasEsc = false;
    let hasRou = false;
    for (let i = 0; i < fixtures.length; i += 1) {
      const fx = fixtures[i];
      if (!fx || typeof fx !== "object") {
        addIssue(`fixture[${i}] must be an object`);
        continue;
      }
      const fxId = String(fx.id || `FX-${i}`);
      const sample = String(fx.sample_input || "");
      if (!sample.includes("SYNTHETIC") && !sample.includes(CASE_MARK)) {
        addIssue(`fixture '${fxId}' sample_input must carry the practice-case mark ("Practice case: an example, not a real person or case.")`);
      }
      if (fx.expected_human_escalation === true) hasEsc = true;
      if (fx.expected_human_escalation === false) hasRou = true;
    }
    if (!(hasEsc && hasRou)) {
      addIssue("fixtures must cover both a routine agent-assisted case and a human-escalation case");
    }
  }

  if (!Array.isArray(raw.sources) || raw.sources.length < 1) {
    addIssue("at least one HTTPS primary source is required");
  } else {
    for (const src of raw.sources) {
      if (!src || typeof src.url !== "string" || !src.url.startsWith("https://")) {
        addIssue("every source url must start with https://");
        break;
      }
    }
  }

  const skills = [...(raw.skill ? [raw.skill] : []), ...(Array.isArray(raw.skills) ? raw.skills : [])];
  const tools = [...(raw.tool ? [raw.tool] : []), ...(Array.isArray(raw.tools) ? raw.tools : [])];
  const artifacts = Array.isArray(raw.artifacts) ? raw.artifacts : [];
  if (skills.length === 0 && tools.length === 0 && artifacts.length === 0) {
    addIssue("at least one skill, MCP tool, or custom artifact is required");
  }
  for (const t of tools) {
    if (!t || typeof t !== "object") continue;
    if (t.read_only === false) {
      addIssue(`MCPToolSpec '${t.name || "tool"}' read_only must be true`);
    }
    const props = t.input_schema && typeof t.input_schema === "object" ? t.input_schema.properties : null;
    if (
      !t.input_schema ||
      t.input_schema.type !== "object" ||
      !props ||
      typeof props !== "object" ||
      Object.keys(props).length === 0
    ) {
      addIssue(`tool '${t.name || "tool"}' input_schema.properties must define at least one field`);
    }
  }

  if (!effectiveTrackId) {
    addIssue("track_id is required to verify track boundaries");
  } else {
    if (explicitTrackId && payloadTrackId && payloadTrackId !== explicitTrackId) {
      addIssue(`draft track_id '${payloadTrackId}' does not match requested track '${explicitTrackId}'`);
    }
    const track = tracksById.get(effectiveTrackId);
    if (!track) {
      addIssue(`unknown track '${effectiveTrackId}'`);
    } else {
      if (raw.domain && raw.domain !== track.domain) {
        addIssue(`draft domain '${raw.domain}' does not match track domain '${track.domain}'`);
      }
      if (Array.isArray(steps) && Array.isArray(track.required_human_only)) {
        const presentKinds = new Set(steps.filter((s) => s && typeof s === "object").map((s) => String(s.kind || "")));
        const missing = track.required_human_only.filter((k) => !presentKinds.has(k));
        if (missing.length > 0) {
          addIssue(`kit must explicitly declare track-required human_only step kinds: ${missing.join(", ")}`);
        }
      }
    }
  }

  const passed = issues.length === 0;
  const receiptSha256 = await sha256Hex(
    canonicalJson({
      issues,
      kit_id: kitId,
      passed,
      persisted: false,
      spdx_license: spdxLicense,
      track_id: effectiveTrackId,
    })
  );

  return {
    passed,
    persisted: false,
    kit_id: kitId,
    track_id: effectiveTrackId,
    spdx_license: spdxLicense,
    issues,
    checks_run: PRACTICE_CHECKS,
    receipt_sha256: receiptSha256,
    receipt_scope: "validation_outcome",
    artifact_bound: false,
  };
}

function buildStaticAgentCard(request) {
  const origin = new URL(request.url).origin;
  return {
    schema_version: "1.0",
    name: "Eranos",
    surface_id: "surface:eranos",
    description:
      "Two-sided marketplace where people donate spare AI capacity and their agents build, deterministically check, and independently review (drafter != reviewer) agent kits for nonprofits, NGOs and public-good groups. A kit bundles instructions, skills, knowledge, read-only service connections, a step map with person-only steps, and synthetic checks and tests.",
    version: ERANOS_VERSION,
    url: origin,
    spdx_allowlist: Array.from(OPEN_SPDX_ALLOWLIST).sort(),
    headers: { surface: "X-Surface-Id" },
    endpoints: {
      mcp: "/mcp",
      catalog: "/api/catalog",
      tracks: "/api/tracks",
      practice: "/api/practice",
      handshake: "/api/handshake",
      feed: "/api/feed",
      health: "/healthz",
      llms: "/llms.txt",
      llms_full: "/llms-full.txt",
      agent_guide: "/agent.md",
      connect: "/connect.json",
      ask: "/nonprofits",
      request_page: "/requests/{request_id}",
      request: "/api/requests/{request_id}",
      request_history: "/api/nouns/eranos.requests/{request_id}/history",
      open_tasks: "/api/open-tasks",
      process_markdown: "/p/{request_id}/agent.md",
      practice_cases: "/p/{request_id}/practice.md",
      process_download: "/p/{request_id or catalog_key}/download",
    },
    access: accessDescriptor("eranos"),
    capabilities: {
      streaming: false,
      pushNotifications: false,
      statelessMcp: true,
      zeroStoragePracticeGate: true,
    },
    skills: [
      {
        id: "list_tracks",
        name: "List Public-Good Tracks",
        description: "List NGO and nonprofit build tracks and required human_only boundaries.",
      },
      {
        id: "search_catalog",
        name: "Search Verified Kit Catalog",
        description: "Filter two-step verified NGO kits by domain, track, tag, cohort, SPDX license, or query.",
      },
      {
        id: "get_kit",
        name: "Get Verified Kit Bundle",
        description: "Fetch a full PublishedKit including skills, read-only MCP schemas, checklists, fixtures, and receipts.",
      },
      {
        id: "practice_verify_kit",
        name: "Zero-Storage Practice Verifier",
        description: "Run deterministic boundary, copy, SPDX, and fixture verification in memory (persisted: false).",
      },
    ],
  };
}

function buildAgentCard(request) {
  const card = buildStaticAgentCard(request);
  card.skills = MCP_TOOLS.map((tool) => ({id: tool.name, name: tool.name, description: tool.description}));
  card.access = accessDescriptor("eranos");
  return card;
}

function jsonRpcError(id, code, message, status = 200) {
  return jsonResp({ jsonrpc: "2.0", id: id ?? null, error: { code, message } }, status);
}

async function lookupSingleKit(request, env, kitId, cohort = null) {
  const filters = new URL(request.url).searchParams;
  if (cohort) filters.set("cohort", cohort);
  const visible = (entry) => entry && filterCatalogKits([entry], filters).length === 1;
  if (env && env.FABRIC_DB) {
    const found = await getHeadRecord(env.FABRIC_DB, "eranos.catalog", kitId);
    return visible(found) ? found : null;
  }
  const snapItem = await fetchAssetJson(request, env, `/snapshot/catalog/${encodeURIComponent(kitId)}.json`);
  if (visible(snapItem)) return snapItem;
  return null;
}

async function handleMcp(request, env) {
  if (request.method !== "POST") {
    return problem(405, "Method Not Allowed", "MCP endpoint requires POST JSON-RPC 2.0.", "method_not_allowed", {
      allow: "POST",
    });
  }
  let body;
  try {
    body = internalWords(await request.json());
  } catch {
    return jsonRpcError(null, -32700, "Parse error", 400);
  }
  if (!body || typeof body !== "object" || Array.isArray(body) || body.jsonrpc !== "2.0" || typeof body.method !== "string") {
    return jsonRpcError(body?.id ?? null, -32600, "Invalid Request", 400);
  }

  const method = body.method;
  const hasId = Object.prototype.hasOwnProperty.call(body, "id") && body.id !== null && body.id !== undefined;
  const reqId = body.id ?? null;
  const params = body.params && typeof body.params === "object" && !Array.isArray(body.params) ? body.params : {};

  if (method === "initialize") {
    const requestedProto = String(params.protocolVersion || "2024-11-05");
    const protocolVersion = SUPPORTED_MCP_PROTOCOLS.has(requestedProto) ? requestedProto : "2024-11-05";
    return jsonResp({
      jsonrpc: "2.0",
      id: reqId,
      result: {
        protocolVersion,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "eranos", version: ERANOS_VERSION },
        instructions:
          "Eranos public-good NGO catalog and zero-storage practice verifier (persisted: false). Every fixture is a practice case (an example, not a real person or case); human_only boundaries stay strictly with trained staff.",
      },
    });
  }

  if (method === "notifications/initialized" || method.startsWith("notifications/")) {
    if (!hasId) return jsonResp({ jsonrpc: "2.0", result: {} }, 202);
    return jsonResp({ jsonrpc: "2.0", id: reqId, result: {} });
  }

  if (method === "ping") {
    return jsonResp({ jsonrpc: "2.0", id: reqId, result: {} });
  }

  if (method === "tools/list") {
    return jsonResp({ jsonrpc: "2.0", id: reqId, result: { tools: MCP_TOOLS } });
  }

  if (method === "tools/call") {
    const toolName = String(params.name || "");
    const args = params.arguments && typeof params.arguments === "object" && !Array.isArray(params.arguments) ? params.arguments : {};

    if (toolName === "list_tracks") {
      const payload = await loadTracksPayload(request, env);
      return jsonResp({
        jsonrpc: "2.0",
        id: reqId,
        result: {
          content: [{ type: "text", text: JSON.stringify(payload) }],
          structuredContent: payload,
          isError: false,
        },
      });
    }

    if (toolName === "search_catalog") {
      const rawKits = await loadRawCatalogList(request, env);
      const sp = new URLSearchParams();
      for (const k of ["domain", "track", "tag", "cohort", "spdx", "q"]) {
        if (typeof args[k] === "string" && args[k].trim()) sp.set(k, args[k]);
      }
      const kits = filterCatalogKits(rawKits, sp);
      const payload = { synthetic: true, two_step_verified: true, kits };
      return jsonResp({
        jsonrpc: "2.0",
        id: reqId,
        result: {
          content: [{ type: "text", text: JSON.stringify(payload) }],
          structuredContent: payload,
          isError: false,
        },
      });
    }

    if (toolName === "get_kit") {
      const kitId = String(args.kit_id || "").trim();
      if (!KIT_ID_RE.test(kitId)) {
        const errPayload = { error: "invalid kit id", kit_id: kitId };
        return jsonResp({
          jsonrpc: "2.0",
          id: reqId,
          result: {
            content: [{ type: "text", text: JSON.stringify(errPayload) }],
            structuredContent: errPayload,
            isError: true,
          },
        });
      }
      const found = await lookupSingleKit(request, env, kitId, args.cohort);
      if (!found) {
        const errPayload = { error: `kit ${kitId} is not in the catalog`, kit_id: kitId };
        return jsonResp({
          jsonrpc: "2.0",
          id: reqId,
          result: {
            content: [{ type: "text", text: JSON.stringify(errPayload) }],
            structuredContent: errPayload,
            isError: true,
          },
        });
      }
      const payload = { synthetic: true, ...found };
      return jsonResp({
        jsonrpc: "2.0",
        id: reqId,
        result: {
          content: [{ type: "text", text: JSON.stringify(payload) }],
          structuredContent: payload,
          isError: false,
        },
      });
    }

    if (toolName === "practice_verify_kit") {
      const tracksPayload = await loadTracksPayload(request, env);
      const tracksById = new Map((tracksPayload.tracks || []).map((t) => [t.id, t]));
      const draftInput = args.draft && typeof args.draft === "object" ? args.draft : args;
      const explicitTrack = typeof args.track_id === "string" && args.track_id.trim() ? args.track_id.trim() : null;
      const payload = await withDraftDigest(await practiceVerifyKit(draftInput, explicitTrack, tracksById), args);
      return jsonResp({
        jsonrpc: "2.0",
        id: reqId,
        result: {
          content: [{ type: "text", text: JSON.stringify(payload) }],
          structuredContent: payload,
          isError: false,
        },
      });
    }

    return jsonRpcError(reqId, -32602, `Unknown tool: ${toolName}`);
  }

  return jsonRpcError(reqId, -32601, `Method not found: ${method}`);
}

async function handleCloudApi(request, env, pathname) {
  if (pathname === "/api/practice") {
    if (request.method !== "POST") {
      return problem(405, "Method Not Allowed", "POST JSON draft payload to /api/practice.", "method_not_allowed", {
        allow: "POST",
      });
    }
    let body;
    try {
      body = internalWords(await request.json());
    } catch {
      return problem(400, "Bad Request", "invalid JSON payload", "invalid_request");
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return problem(400, "Bad Request", "practice payload must be a JSON object", "invalid_request");
    }
    const reqUrl = new URL(request.url);
    const queryTrack = (reqUrl.searchParams.get("track_id") || "").trim();
    const bodyTrack =
      "draft" in body && typeof body.track_id === "string" && body.track_id.trim() ? body.track_id.trim() : "";
    const tracksPayload = await loadTracksPayload(request, env);
    const tracksById = new Map((tracksPayload.tracks || []).map((t) => [t.id, t]));
    const result = await practiceVerifyKit(body, queryTrack || bodyTrack || null, tracksById);
    return jsonResp(await withDraftDigest(result, body));
  }

  if (request.method !== "GET" && request.method !== "HEAD" && !(pathname === "/api/handshake" && request.method === "POST")) {
    return problem(405, "Method Not Allowed", "Eranos public API routes are read-only GET/HEAD.", "method_not_allowed", {
      allow: "GET, HEAD",
    });
  }

  if (pathname === "/api/health") {
    return jsonResp({
      ok: true,
      synthetic: true,
      surface: "eranos",
      version: ERANOS_VERSION,
      backend: "tessera-cloud",
    });
  }

  if (pathname === "/api/handshake") {
    // At most 10 a minute from one address; the negotiation with Tessera and Herma is cached for 5 minutes, and a
    // tracked anonymous session is minted only on POST. Only the public handshake fields are returned: never a
    // surface key's grants (queues, stores, scopes).
    if (handshakeRateLimited(request)) {
      return problem(429, "Too Many Requests", "Too many handshakes from this address; try again in a minute.", "rate_limited", { "retry-after": "60" });
    }
    const negotiation = await cachedNegotiation(env);
    let tesseraSession = null;
    if (request.method === "POST" && env.TESSERA) {
      let agentLabel = "external-agent";
      try {
        const reqJson = await request.clone().json();
        const rawLabel = reqJson?.agent_label || reqJson?.agent || reqJson?.model;
        if (typeof rawLabel === "string" && rawLabel.trim()) {
          agentLabel = rawLabel.trim().slice(0, 48).replace(/[^a-zA-Z0-9._-]/g, "-");
        }
      } catch {
        // empty or non-JSON body still gets default label
      }
      try {
        const sHeaders = { "Content-Type": "application/json" };
        const clientIp = request.headers.get("CF-Connecting-IP");
        if (clientIp) sHeaders["CF-Connecting-IP"] = clientIp;
        const sResp = await env.TESSERA.fetch("https://tessera.ta-amps.workers.dev/v1/session/anonymous", {
          method: "POST",
          headers: sHeaders,
          body: JSON.stringify({ agent_label: agentLabel }),
        });
        if (sResp.ok) {
          const parsedSession = await sResp.json();
          if (parsedSession && typeof parsedSession === "object") tesseraSession = parsedSession;
        } else {
          await sResp.body?.cancel();
        }
      } catch {
        // graceful fallback if anonymous session minting is rate-limited
      }
    }
    return jsonResp({
      ...negotiation,
      ...(tesseraSession
        ? {
            session_id: tesseraSession.session_id,
            session_token: tesseraSession.session_token,
            tessera_namespace: tesseraSession.namespace,
            tessera_session: tesseraSession,
          }
        : {}),
    });
  }

  if (pathname === "/api/tracks") {
    return jsonResp(await loadTracksPayload(request, env));
  }

  if (pathname === "/api/examples") {
    // Example needs and recorded example runs are repository nouns, built into this deploy's snapshot.
    const examples = await fetchAssetJson(request, env, "/snapshot/examples.json");
    if (!examples) {
      return problem(404, "Not Found", "this build has no example nouns", "not_found");
    }
    return jsonResp(examples);
  }

  const historyMatch = /^\/api\/nouns\/([a-z0-9_.-]+)\/([^/]+)\/history$/.exec(pathname);
  if (historyMatch) {
    const store = historyMatch[1];
    const key = decodeSegment(historyMatch[2]);
    if (key === BROKEN_ESCAPE) {
      return problem(400, "Bad Request", "the noun key is not valid percent-encoding", "invalid_request");
    }
    if (!HISTORY_STORES.has(store) || !NOUN_KEY_RE.test(key)) {
      return problem(404, "Not Found", "no such public record history", "not_found");
    }
    return edgeCached(request, async () => {
      const versions = await readRecordHistory(env.FABRIC_DB, store, key);
      return versions ? jsonResp({ synthetic: false, store, key, versions }) : problem(404, "Not Found", "no such public record history", "not_found");
    });
  }

  if (pathname === "/api/open-tasks") {
    let reachable = false;
    const tasks = [];
    if (env.TESSERA && env.TESSERA_SURFACE_KEY) {
      for (const queue of OPEN_TASK_QUEUES) {
        try {
          const resp = await env.TESSERA.fetch(`https://tessera.ta-amps.workers.dev/ns/main/v1/verbs?queue=${queue}&status=ready&limit=20`, {
            headers: { Authorization: `Bearer ${env.TESSERA_SURFACE_KEY}`, "X-Surface-Id": "eranos" },
          });
          if (resp.ok) {
            reachable = true;
            const body = await resp.json();
            for (const verb of Array.isArray(body.verbs) ? body.verbs : []) tasks.push(openTaskView(verb, queue));
          } else {
            await resp.body?.cancel();
          }
        } catch {
          // an unreachable queue is reported below, never as an empty list
        }
      }
    }
    if (!reachable) return problem(503, "Service Unavailable", "the open tasks can't be read right now", "unavailable");
    return jsonResp({ synthetic: false, tasks });
  }

  const nounMatch = /^\/api\/nouns\/([a-z0-9_.-]+)(?:\/([^/]+))?$/.exec(pathname);
  if (nounMatch) {
    const store = nounMatch[1];
    const key = nounMatch[2] === undefined ? null : decodeSegment(nounMatch[2]);
    if (key === BROKEN_ESCAPE) {
      return problem(400, "Bad Request", "the noun key is not valid percent-encoding", "invalid_request");
    }
    if (!PUBLIC_NOUN_STORES.has(store) || (key !== null && !NOUN_KEY_RE.test(key))) {
      return problem(404, "Not Found", "no such public noun", "not_found");
    }
    if (key === null) return edgeCached(request, async () => jsonResp(await loadNounList(request, env, store)));
    if (store === "eranos.requests" && SHORT_BADGE_RE.test(key)) {
      return problem(
        404,
        "Not Found",
        `${key} is the 4-character display badge; pass the full rq-... request_id from the /requests/rq-... URL.`,
        "not_found"
      );
    }
    return edgeCached(request, async () => {
      const found = await loadNoun(request, env, store, key);
      if (found) return jsonResp(found);
      if (store === "eranos.requests") {
        const pending = await fetchPendingRequestVerb(env, key);
        if (pending) {
          return problem(
            404,
            "Not Found",
            `request ${key} is queued on eq01 (${pending.state}) awaiting volunteer scope planning; no public eranos.requests noun exists until screened; poll /api/requests/${key} for immediate read-after-write status.`,
            "pending_scope_plan"
          );
        }
      }
      return problem(404, "Not Found", "no such public noun", "not_found");
    });
  }

  if (pathname === "/api/requests") {
    return jsonResp(await loadRequestsPayload(request, env));
  }

  // /api/requests/<id>: one request as its public records hold it (the eranos.requests noun and the versions the
  // volunteer worker wrote), the real queued eq01 verb while awaiting scope planning, or the example request for the
  // example addresses. Nothing here is made up per id.
  const reqStatusMatch = /^\/api\/requests\/([^/]+)$/.exec(pathname);
  if (reqStatusMatch) {
    const reqId = decodeSegment(reqStatusMatch[1]);
    if (reqId === BROKEN_ESCAPE || !NOUN_KEY_RE.test(reqId)) {
      return problem(400, "Bad Request", "invalid request id", "invalid_request");
    }
    if (Object.prototype.hasOwnProperty.call(EXAMPLE_REQUEST_ALIASES, reqId)) {
      const example = await loadNoun(request, env, "eranos.instructions", EXAMPLE_REQUEST_ALIASES[reqId]);
      if (!example) return problem(404, "Not Found", "the example request is not in this build", "not_found");
      return jsonResp({ example: true, request_id: reqId, page: `/requests/${encodeURIComponent(reqId)}`, value: example.value });
    }
    if (SHORT_BADGE_RE.test(reqId)) {
      return problem(
        404,
        "Not Found",
        `${reqId} is the 4-character display badge; pass the full rq-... request_id from the /requests/rq-... URL.`,
        "not_found"
      );
    }
    return edgeCached(request, async () => {
      const record = await loadNoun(request, env, "eranos.requests", reqId).catch(() => null);
      if (!record) {
        const pending = await fetchPendingRequestVerb(env, reqId);
        if (pending) {
          const resp = jsonResp({
            example: false,
            pending_plan: true,
            request_id: reqId,
            page: `/requests/${encodeURIComponent(reqId)}`,
            noun_url: `/api/nouns/eranos.requests/${encodeURIComponent(reqId)}`,
            value: {
              schema_version: 1,
              request_id: reqId,
              status: "received",
              queue_state: pending.state,
              text: null,
              ...(pending.output_type ? { output_type: pending.output_type } : {}),
              ...(pending.frequency ? { frequency: pending.frequency } : {}),
              events: [{ type: "received", at: pending.created_at, ref: reqId }],
            },
            versions: [],
          });
          resp.headers.set("x-skip-edge-cache", "1");
          return resp;
        }
        return problem(404, "Not Found", `request ${reqId} is not found`, "not_found");
      }
      const history = await readRecordHistory(env.FABRIC_DB, "eranos.requests", reqId).catch(() => null);
      const versions =
        history ||
        (record.version ? [{ version: Number(record.version), created_at: 0, value: record.value }] : []);
      return jsonResp({
        example: false,
        pending_plan: false,
        request_id: reqId,
        page: `/requests/${encodeURIComponent(reqId)}`,
        value: record.value,
        versions,
      });
    });
  }

  if (pathname === "/api/catalog") {
    const reqUrl = new URL(request.url);
    const rawKits = await loadRawCatalogList(request, env);
    const kits = filterCatalogKits(rawKits, reqUrl.searchParams);
    return jsonResp({
      synthetic: true,
      two_step_verified: true,
      kits,
    });
  }

  const kitMatch = /^\/api\/catalog\/([^/]+)$/.exec(pathname);
  if (kitMatch) {
    const kitId = decodeSegment(kitMatch[1]);
    if (kitId === BROKEN_ESCAPE || !KIT_ID_RE.test(kitId)) {
      return problem(400, "Bad Request", "invalid kit id", "invalid_request");
    }
    const found = await lookupSingleKit(request, env, kitId);
    if (!found) {
      return problem(404, "Not Found", `kit ${kitId} is not in the catalog`, "not_found");
    }
    return jsonResp({ synthetic: true, ...found });
  }

  if (pathname === "/api/fabric") {
    let queues = [];
    if (env.TESSERA) {
      try {
        const resp = await env.TESSERA.fetch("https://tessera.ta-amps.workers.dev/v1/health", {
          headers: { "X-Surface-Id": "eranos" },
        });
        if (resp.ok) {
          const h = await resp.json();
          const byName = new Map((h.queues || []).map((q) => [q.name, q.counts || {}]));
          queues = ERANOS_QUEUE_LABELS.map(([name, label]) => ({
            name,
            label,
            ...ZERO_QUEUE_COUNTS,
            ...(byName.get(name) || {}),
          }));
        } else {
          await resp.body?.cancel();
        }
      } catch {
        // fall back to empty queue array if service binding unreachable
      }
    }
    return jsonResp({
      display_name: "Tessera Cloud",
      plan: "tessera-cloud",
      synthetic: true,
      queues,
    });
  }

  if (pathname === "/api/feed") {
    const reqUrl = new URL(request.url);
    const rawAfter = Number.parseInt(reqUrl.searchParams.get("after") ?? "0", 10);
    const rawLimit = Number.parseInt(reqUrl.searchParams.get("limit") ?? "20", 10);
    const after = Number.isFinite(rawAfter) && rawAfter >= 0 ? rawAfter : 0;
    const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 200) : 20;
    const fallbackFeed = {
      synthetic: true,
      feed: "noun.promotions",
      entries: [],
      next_cursor: after,
    };
    if (env.TESSERA) {
      try {
        const headers = { "X-Surface-Id": "eranos" };
        if (env.TESSERA_SURFACE_KEY) {
          headers["Authorization"] = `Bearer ${env.TESSERA_SURFACE_KEY}`;
        }
        const resp = await env.TESSERA.fetch(
          `https://tessera.ta-amps.workers.dev/v1/feeds/noun.promotions?after=${after}&limit=${limit}`,
          { headers }
        );
        if (resp.ok) {
          const payload = await resp.json();
          if (payload && typeof payload === "object") {
            return jsonResp(publicFeedPayload(payload, after));
          }
        } else {
          await resp.body?.cancel();
        }
      } catch {
        // fall back to empty synthetic cursor if service binding unreachable
      }
    }
    return jsonResp(fallbackFeed);
  }

  return problem(404, "Not Found", `No API route matches ${pathname}`, "not_found");
}

async function proxyOrigin(request, env) {
  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, env.API_ORIGIN || DEFAULT_API_ORIGIN);
  const headers = new Headers(request.headers);
  stripHopByHop(headers);
  headers.delete("cookie");
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", incoming.protocol.replace(":", ""));
  if (env.EDGE_SECRET) headers.set("x-edge-auth", env.EDGE_SECRET);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
    });
  } catch {
    return problem(502, "Bad Gateway", "The Eranos API did not answer.", "unavailable");
  }
  const response = new Response(upstream.body, upstream);
  if (!response.headers.has("cache-control")) {
    response.headers.set("cache-control", "private, no-store");
  }
  return response;
}

async function handleDiscoveryRoute(request, env, pathname) {
  if (pathname === "/mcp") {
    if ((env.STORAGE_MODE || "cloud") === "origin") return proxyOrigin(request, env);
    return handleMcp(request, env);
  }

  if (
    pathname === "/favicon.svg" ||
    pathname === "/healthz" ||
    pathname === "/robots.txt" ||
    pathname === "/llms.txt" ||
    pathname === "/llms-full.txt" ||
    pathname === "/agent.md" ||
    pathname === "/.well-known/agent-card.json" ||
    pathname === "/.well-known/agent.json" ||
    pathname === "/.well-known/security.txt" ||
    PROCESS_DOC_RE.test(pathname) ||
    PACKAGE_DOWNLOAD_RE.test(pathname)
  ) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405, headers: { allow: "GET, HEAD" } });
    }
    if (pathname === "/favicon.svg") {
      return textResp(FAVICON_SVG, "image/svg+xml; charset=utf-8");
    }
    if (pathname === "/healthz") {
      return jsonResp({
        ok: true,
        status: "ok",
        synthetic: true,
        surface: "eranos",
        version: ERANOS_VERSION,
        backend: (env.STORAGE_MODE || "cloud") === "origin" ? "origin" : "tessera-cloud",
      });
    }
    if (pathname === "/robots.txt") {
      return textResp(ROBOTS_TXT, "text/plain; charset=utf-8");
    }
    if (pathname === "/.well-known/security.txt") {
      return textResp(SECURITY_TXT, "text/plain; charset=utf-8");
    }
    const download = PACKAGE_DOWNLOAD_RE.exec(pathname);
    if (download) return servePackage(request, env, download[1]);
    const processDoc = PROCESS_DOC_RE.exec(pathname);
    if (processDoc) {
      const id = processDoc[1];
      const part = Number(new URL(request.url).searchParams.get("part")) || 1;
      const found = await loadProcessResult(request, env, id, part);
      const origin = new URL(request.url).origin;
      const pkg = processDoc[2] === "agent" ? await publishedPackage(request, env, id) : null;
      const download = pkg
        ? `\n## Download the process\n${origin}/p/${id}/download${part > 1 ? `?part=${part}` : ""}\nSHA-256: ${pkg.value.blob_sha256}. A different volunteer's key reviewed it; check the hash before you run it.\n`
        : "";
      let text = found ? (processDoc[2] === "agent" ? processAgentMarkdown(origin, id, found) + download : processPracticeMarkdown(origin, id, found)) : null;
      if (!text && pkg) {
        const kit = pkg.value.kit || {};
        text = `# ${kit.title || pkg.key}\n\n${kit.summary || ""}\n${download}`;
      }
      return text ? textResp(text, "text/markdown; charset=utf-8") : textResp("No reusable process is published at this address.\n", "text/plain; charset=utf-8", 404);
    }
    if (pathname === "/llms.txt") {
      const noun = await loadNoun(request, env, "eranos.instructions", "llms").catch(() => null);
      const fromNoun = noun && noun.value && typeof noun.value.text === "string" ? noun.value.text : null;
      const fromAsset = fromNoun ? null : await fetchAssetText(request, env, "/llms.txt");
      return textResp((fromNoun || fromAsset || FALLBACK_LLMS_TXT) + "\n## Agent access\nUse /connect.json for access modes. Public tools need no key; tracked anonymous and keyed work connect through https://tessera.ta-amps.workers.dev/connect.\n", "text/plain; charset=utf-8");
    }
    if (pathname === "/llms-full.txt") {
      const fromAsset = await fetchAssetText(request, env, "/llms-full.txt");
      return textResp((fromAsset || FALLBACK_LLMS_FULL_TXT) + "\nAccess modes: /connect.json.\n", "text/plain; charset=utf-8");
    }
    if (pathname === "/agent.md") {
      const noun = await loadNoun(request, env, "eranos.instructions", "llms").catch(() => null);
      const guide = noun && noun.value && typeof noun.value.text === "string" ? noun.value.text : FALLBACK_LLMS_TXT;
      return textResp(
        `${guide}\n## Agent access\n- Discovery: /connect.json, /.well-known/agent.json (also /.well-known/agent-card.json).\n- A tracked anonymous session: POST /api/handshake; Eranos asks Tessera to mint it and returns what Tessera answers.\n- One request: /api/requests/<request id> returns its public record and recorded versions.\n`,
        "text/markdown; charset=utf-8",
      );
    }
    if (pathname === "/.well-known/agent-card.json" || pathname === "/.well-known/agent.json") {
      return jsonResp(buildAgentCard(request));
    }
  }
  return null;
}

const onboardingApplication = {
  async fetch(request, env = {}) {
    const { pathname } = new URL(request.url);
    if (pathname.replace(/\/+$/, "") === "/connect" && (request.method === "GET" || request.method === "HEAD")) {
      return finish(await connectPage(request, env), request.method);
    }
    const access = accessResponse(request, "eranos");
    if (access) return finish(access, request.method);
    let response = await handleDiscoveryRoute(request, env, pathname);
    if (!response) {
      if (pathname === "/api" || pathname.startsWith("/api/")) {
        if ((env.STORAGE_MODE || "cloud") === "origin") {
          response = await proxyOrigin(request, env);
        } else {
          response = await handleCloudApi(request, env, pathname);
        }
      } else if (request.method === "GET" || request.method === "HEAD") {
        response = env.ASSETS
          ? await env.ASSETS.fetch(request)
          : new Response("Not Found", { status: 404 });
        const html = (response.headers.get("content-type") || "").includes("text/html");
        if (
          response.status === 200 &&
          html &&
          (!isAppPage(pathname) ||
            (await isMissingKitPage(request, env, pathname)))
        ) {
          response = new Response(response.body, { status: 404, statusText: "Not Found", headers: response.headers });
        }
      } else {
        response = new Response("Method Not Allowed", { status: 405, headers: { allow: "GET, HEAD" } });
      }
    }
    return finish(response, request.method);
  },
};

// The vendored onboarding module still serves /agent-start.{js,css,json}. Its landing banner is not
// injected here: the home page opens on the marketplace's two front doors, and the /help page copies the
// same starting brief, built in the browser with this same module.
export default {
  ...onboardingApplication,
  async fetch(request, env, ctx) {
    return agentStartAsset(request) || onboardingApplication.fetch(request, env, ctx);
  },
};
