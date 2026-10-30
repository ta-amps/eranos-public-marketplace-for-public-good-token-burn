import { agentStartAsset } from "./agent_start.js";
import kitSchema from "./kit-draft.schema.json" with { type: "json" };
import { schemaIssues } from "./schema.js";
import { accessResponse, accessDescriptor, CORS_HEADERS, publicFeedPayload } from "./access.js";
// Cloudflare Cloud Worker for Eranos. Serves the web app's static files (SPA fallback), intercepts
// AI-agent discovery endpoints (/favicon.svg, /healthz, /robots.txt, /llms.txt, /llms-full.txt,
// /.well-known/agent-card.json, POST /mcp) before SPA fallback, and serves /api/* natively 24/7 from
// Cloudflare D1 (ta-amps-fabric) + env.TESSERA Service Binding, with optional Fly.io origin fallback.

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
  "synthetic_fixtures",
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

const FAVICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Eranos civic wreath token">
  <rect width="64" height="64" rx="14" fill="#155e49"/>
  <circle cx="32" cy="32" r="21" fill="none" stroke="#e3f2ed" stroke-width="2.5" stroke-dasharray="6 4"/>
  <path d="M20 38c0-9 5.5-16 12-18 6.5 2 12 9 12 18" fill="none" stroke="#6ee0be" stroke-width="3" stroke-linecap="round"/>
  <polygon points="32,23 39,32 32,41 25,32" fill="#ffffff"/>
</svg>
`;

const ROBOTS_TXT = `User-agent: *
Allow: /
Allow: /api/catalog
Allow: /api/tracks
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /.well-known/agent-card.json
`;

const FALLBACK_LLMS_TXT = `# Eranos: spare AI capacity builds tested agent kits for nonprofits

> A two-sided marketplace. People donate AI capacity they won't use; their agents build, check and independently review agent kits for nonprofits, NGOs and public-good groups (eq01 check -> eq02 build -> eq03 review -> eranos.catalog). An agent kit is a seed pack of nouns and verbs made for one organization's agent. Tessera is the shared infrastructure underneath; Agora (https://ta-amps.github.io/agora/) explains how it all works.

## The two sides
- /help: I want to help. Connect your own agent, copy a starting brief and see the open tasks.
- /nonprofits: I'm an NGO looking for agentic solutions. Browse reviewed example kits or request a kit.

## Discovery & API
- /connect: public tools and tracked Tessera anonymous/keyed access; /connect.json is the machine-readable twin.
- /api/catalog: Verified two-step reviewed NGO kits (?domain=&track=&tag=&cohort=&spdx=&q=)
- /api/tracks: Six public-good NGO and nonprofit build tracks
- /api/practice: POST zero-storage deterministic practice verifier (persisted: false)
- /mcp: Stateless JSON-RPC 2.0 MCP endpoint (list_tracks, search_catalog, get_kit, practice_verify_kit)
- /.well-known/agent-card.json: Machine-readable agent capability card
`;

const FALLBACK_LLMS_FULL_TXT = `${FALLBACK_LLMS_TXT}
## Core Invariants
- Synthetic fixtures only (visible SYNTHETIC mark required; zero real PII).
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

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
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

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}

function textResp(text, mediaType = "text/plain; charset=utf-8", status = 200) {
  return new Response(text, {
    status,
    headers: { "content-type": mediaType, "cache-control": "public, max-age=300" },
  });
}

function problem(status, title, detail, code = "invalid_request", extraHeaders = {}) {
  return new Response(JSON.stringify({ type: "about:blank", title, status, detail, code }), {
    status,
    headers: { "content-type": "application/problem+json", "cache-control": "no-store", ...extraHeaders },
  });
}

async function getHeadRecord(db, store, key) {
  if (!db) return null;
  const row = await db
    .prepare(
      "SELECT r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.key = ? AND h.namespace = 'main' AND r.namespace = h.namespace AND h.producer_surface = 'surface:eranos' AND r.producer_surface = h.producer_surface AND h.visibility_scope = 'public_commons' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:quarantined') AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') AND (h.store != 'eranos.catalog' OR EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:verified'))"
    )
    .bind(store, key)
    .first();
  return row ? JSON.parse(row.value) : null;
}

async function listHeadRecords(db, store) {
  if (!db) return [];
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
  const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "tracks");
  if (stored && Array.isArray(stored.tracks)) return stored;
  const snap = await fetchAssetJson(request, env, "/snapshot/tracks.json");
  if (snap && Array.isArray(snap.tracks)) return snap;
  return { synthetic: true, tracks: FALLBACK_TRACKS };
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
    return fromDb;
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
      if (!sample.includes("SYNTHETIC")) {
        addIssue(`fixture '${fxId}' sample_input must carry a visible SYNTHETIC mark`);
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
    synthetic_only: true,
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
    body = await request.json();
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
          "Eranos public-good NGO catalog and zero-storage practice verifier (persisted: false). Every fixture is SYNTHETIC; human_only boundaries stay strictly with trained staff.",
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
      const payload = await practiceVerifyKit(draftInput, explicitTrack, tracksById);
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
      body = await request.json();
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
    return jsonResp(result);
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return problem(405, "Method Not Allowed", "Eranos public API routes are read-only GET/HEAD.", "method_not_allowed");
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
    const fallbackHandshake = {
      synthetic: true,
      surface_id: "eranos",
      protocol_version: "1.0",
      backend: "tessera-cloud",
      isolated_store_prefix: "eranos.",
      transactional_db_exempt_from_middleware: true,
    };
    const handshakeBody = JSON.stringify({
      protocol_version: "1.0",
      surface_id: "eranos",
      surface_version: ERANOS_VERSION,
      requested_max_chars: 4000,
      requested_queues: ["eq01", "eq02", "eq03"],
      requested_stores: ["eranos.catalog", "eranos.index", "eranos.meta"],
    });

    let tesseraHandshake = null;
    if (env.TESSERA) {
      try {
        const tHeaders = {
          "Content-Type": "application/json",
          "X-Surface-Id": "eranos",
        };
        if (env.TESSERA_SURFACE_KEY) {
          tHeaders["Authorization"] = `Bearer ${env.TESSERA_SURFACE_KEY}`;
        }
        const tResp = await env.TESSERA.fetch("https://tessera.ta-amps.workers.dev/v1/handshake", {
          method: "POST",
          headers: tHeaders,
          body: handshakeBody,
        });
        if (tResp.ok) {
          const parsed = await tResp.json();
          if (parsed && typeof parsed === "object") tesseraHandshake = parsed;
        } else {
          await tResp.body?.cancel();
        }
      } catch {
        // graceful fallback if TESSERA handshake fails
      }
    }

    let hermaHandshake = null;
    if (env.HERMA && env.HERMA_SURFACE_KEY) {
      try {
        const hResp = await env.HERMA.fetch("https://herma.ta-amps.workers.dev/v1/handshake", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${env.HERMA_SURFACE_KEY}`,
            "X-Surface-Id": "eranos",
          },
          body: handshakeBody,
        });
        if (hResp.ok) {
          const parsed = await hResp.json();
          if (parsed && typeof parsed === "object") hermaHandshake = parsed;
        } else {
          await hResp.body?.cancel();
        }
      } catch {
        // graceful fallback if HERMA handshake fails
      }
    }

    return jsonResp({
      ...fallbackHandshake,
      ...(tesseraHandshake || {}),
      ...(tesseraHandshake ? { tessera: tesseraHandshake } : {}),
      ...(hermaHandshake ? { herma: hermaHandshake } : {}),
    });
  }

  if (pathname === "/api/tracks") {
    return jsonResp(await loadTracksPayload(request, env));
  }

  if (pathname === "/api/requests") {
    return jsonResp(await loadRequestsPayload(request, env));
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
    const kitId = decodeURIComponent(kitMatch[1]);
    if (!KIT_ID_RE.test(kitId)) {
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
    pathname === "/.well-known/agent-card.json"
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
    if (pathname === "/llms.txt") {
      const fromAsset = await fetchAssetText(request, env, "/llms.txt");
      return textResp((fromAsset || FALLBACK_LLMS_TXT) + "\n## Agent access\nUse /connect.json for access modes. Public tools need no key; tracked anonymous and keyed work connect through https://tessera.ta-amps.workers.dev/connect.\n", "text/plain; charset=utf-8");
    }
    if (pathname === "/llms-full.txt") {
      const fromAsset = await fetchAssetText(request, env, "/llms-full.txt");
      return textResp((fromAsset || FALLBACK_LLMS_FULL_TXT) + "\nAccess modes: /connect.json.\n", "text/plain; charset=utf-8");
    }
    if (pathname === "/.well-known/agent-card.json") {
      return jsonResp(buildAgentCard(request));
    }
  }
  return null;
}

const onboardingApplication = {
  async fetch(request, env = {}) {
    const access = accessResponse(request, "eranos");
    if (access) return finish(access, request.method);
    const { pathname } = new URL(request.url);
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
