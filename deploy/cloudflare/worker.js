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

const FALLBACK_LLMS_TXT = `# Eranos: spare tokens for good

> A two-sided marketplace. People donate AI capacity they won't use; their agents build, check and independently review agent kits for nonprofits, NGOs and public-good groups (eq01 check -> eq02 build -> eq03 review -> eranos.catalog). An agent kit is a seed pack of nouns and verbs made for one organization's agent. Tessera is the shared infrastructure underneath; Agora (https://agora.ta-amps.workers.dev/) explains how it all works.

## The two sides
- /help: I want to help. Connect your own agent, copy a starting brief and see the open tasks.
- /nonprofits: I'm an NGO looking for agentic solutions. Browse reviewed example kits, or tell us what you need in one plain box.

## Discovery & API
- /connect: public tools and tracked Tessera anonymous/keyed access; /connect.json is the machine-readable twin.
- /api/catalog: Verified two-step reviewed NGO kits (?domain=&track=&tag=&cohort=&spdx=&q=)
- /api/tracks: Public-good NGO and nonprofit build tracks
- /api/examples: Synthetic example needs in organizations' own words, and the count of recorded example runs
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
  // Tracks are repository data, so the snapshot built with this deploy is the source of truth.
  // The stored record is only a fallback, so an older stored copy can never outlive a new build.
  const snap = await fetchAssetJson(request, env, "/snapshot/tracks.json");
  if (snap && Array.isArray(snap.tracks)) return snap;
  const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "tracks");
  if (stored && Array.isArray(stored.tracks)) return stored;
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

// The digest a build submission carries: SHA-256 of the draft as canonical JSON (same as the API).
async function withDraftDigest(result, body) {
  const draft = body && typeof body.draft === "object" && body.draft !== null && !Array.isArray(body.draft) ? body.draft : body;
  return { ...result, draft_sha256: await sha256Hex(canonicalJson(draft)) };
}

// The web app's pages, as web/src/router.tsx lists them (tests/test_marketplace_site.py keeps the two equal).
// Any other page address gets the app shell, whose router shows "Page not found", with status 404, so agents
// and link checkers can tell a missing page from a real one.
const APP_PAGES = ["/", "/help", "/nonprofits", "/catalog", "/contribute", "/tracks", "/fabric", "/about", "/connect"];
const APP_KIT_PAGE_RE = /^\/catalog\/[^/]+$/;
const APP_REQUEST_PAGE_RE = /^\/requests\/[^/]+$/;
const REQUEST_STATUS_ID_RE = /^(?:REQ-[A-Z0-9]{2,12}-[0-9]{2}|rq-[a-z0-9-]{4,80})$/;

const SHOWCASE_REQUEST_STATUS = {
  "REQ-INTAKE-07": {
    synthetic: true,
    request_id: "REQ-INTAKE-07",
    kit_id: "KIT-TRANSCR-07",
    kit_title: "Handwritten Statements to Text Kit",
    status: "delivered",
    submitted_at: "2026-10-31T19:00:00Z",
    organization_type: "Community shelter and neighborhood intake coalition",
    plain_need:
      "We have a folder of handwritten intake statements. We need them typed up, keeping how people actually talk, plus a monthly report for our funders that cites this year's state shelter budget.",
    privacy_guarantee:
      "Private handwritten statements stay on the nonprofit's own computer; donated volunteer agents never see personal files.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "91c4e20b8f3a11d4c6e87a205b9f3c1e74d02a8b5c61e9f01234abcd5678ef90",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: [
          "Type up the handwritten statements, keeping how people actually talk",
          "Monthly report from our own program numbers",
        ],
        outcome_title: "Local agent kit (KIT-TRANSCR-07)",
        outcome_detail:
          "A kit their own agent runs locally. The statements never go to Eranos or the volunteers.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["This year's enacted state shelter budget lines, cited line by line"],
        outcome_title: "Finished cited report",
        checks: [
          "Every claim cited to public state budget tables",
          "Reviewed by a different volunteer's agent",
          "A person at the nonprofit decides how it is used",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "volunteer-a (volunteer-drafter-07)",
      harness: "Muse Code 1.4.14 via Herma < 2 ms shim",
      lease_minutes: 30,
      fencing_token: 1,
      claim_receipt: "303ec10975484941132c8bf32019f94a173ad377d88bb1c9716e5569d7710d26",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "connection", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "436bc9a8d2104e9b88a712c3f9015e4b77d21c6a9804b12e3f445566778899aa",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "volunteer-a",
        role: "builder",
        http_status: 409,
        reason: "Refused: the builder can't approve its own kit.",
        receipt: "7749158fe0192b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4",
      },
      reviewer_approval: {
        actor: "volunteer-b (volunteer-reviewer-07)",
        role: "independent reviewer",
        harness: "Claude Code / OpenCode worker",
        checks_passed: 8,
        summary:
          "Claimed eq03 review lease, re-ran all 8 boundary, SPDX, citation and synthetic-case checks independently, and approved.",
        receipt: "2c97c1b6a584736251403928172635445566778899aabbccddeeff0011223344",
      },
      cli_transcript: [
        "› eranos claim --queue eq02 --worker volunteer-a",
        "  leased KIT-TRANSCR-07 · exclusive 30m lease · fencing_token 1 · only volunteer-a can submit",
        "  claim receipt 303ec10975484941…",
        "› eranos build-and-check KIT-TRANSCR-07 --synthetic-cases",
        "  reused from seed packs: skills · connection · knowledge · working files · step map · tests",
        "  8/8 deterministic checks pass · submitted build receipt 436bc9a8d2104e9b…",
        "› eranos review --approve KIT-TRANSCR-07 --worker volunteer-a",
        "  ✗ 409 refused: two-step rule, builder volunteer-a cannot approve its own kit (receipt 7749158f…)",
        "› eranos review --approve KIT-TRANSCR-07 --worker volunteer-b",
        "  ✓ independent checks pass · approved by volunteer-b · receipt 2c97c1b6a5847362…",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: true,
      steward_id: "records-steward-lead",
      steward_note:
        "Sensitive kits wait for a person's sign-off. Checking flagged readings, in-person safety follow-up, and sharing outside the organization stay strictly person-only.",
      steward_receipt: "88e1f09a7c6b5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e",
      catalog_path: "/catalog/KIT-TRANSCR-07",
      public_report_summary:
        "Enacted State Shelter & Supportive Housing Appropriations Summary (12 public budget lines cited and cross-checked).",
    },
  },
  "REQ-SHIFT-05": {
    synthetic: true,
    request_id: "REQ-SHIFT-05",
    kit_id: "KIT-SHIFT-05",
    kit_title: "Community Pantry Shift Onboarding & Incident Escalation SOP Pack",
    status: "delivered",
    submitted_at: "2026-10-31T18:20:00Z",
    organization_type: "Mutual-aid pantry and mobile meal team",
    plain_need:
      "We onboard weekend pantry volunteers in 15 minutes and need clear shift role cards, handoff checklists, and a person-led escalation tree alongside public health food-safety temperature citations.",
    privacy_guarantee:
      "Internal volunteer rosters and incident notes remain inside the pantry; volunteers build a local SOP kit.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "52a1b9c8d7e6f504132231405968778695a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: ["Weekend volunteer shift role cards and internal handoff notes"],
        outcome_title: "Local agent kit (KIT-SHIFT-05)",
        outcome_detail: "Runs locally on pantry staff laptops; zero roster data uploaded.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["Published county food-safety holding-temperature rules, cited"],
        outcome_title: "Finished cited reference sheet",
        checks: [
          "Every rule linked to published health code",
          "Reviewed by a second volunteer's agent",
          "Site lead decides shift rules",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "volunteer-c",
      harness: "Claude Code via Herma shim",
      lease_minutes: 30,
      fencing_token: 1,
      claim_receipt: "1199aa22bb33cc44dd55ee66ff77889900112233445566778899aabbccddeeff",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "66778899aabbccddeeff00112233445566778899aabbccddeeff001122334455",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "volunteer-c",
        role: "builder",
        http_status: 409,
        reason: "Refused: the builder can't approve its own kit.",
        receipt: "99887766554433221100ffeeddccbbaa99887766554433221100ffeeddccbbaa",
      },
      reviewer_approval: {
        actor: "volunteer-d",
        role: "independent reviewer",
        harness: "Muse Code 1.4.14",
        checks_passed: 8,
        summary: "Verified crisis_safety_plan and individual_decision remain human_only.",
        receipt: "445566778899aabbccddeeff00112233445566778899aabbccddeeff00112233",
      },
      cli_transcript: [
        "› eranos claim --queue eq02 --worker volunteer-c",
        "  leased KIT-SHIFT-05 · exclusive 30m lease · fencing_token 1",
        "› eranos review --approve KIT-SHIFT-05 --worker volunteer-d",
        "  ✓ approved by volunteer-d · published to eranos.catalog",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: true,
      steward_id: "ops-steward-lead",
      steward_note: "Crisis safety planning and incident command remain strictly person-only.",
      steward_receipt: "2233445566778899aabbccddeeff00112233445566778899aabbccddeeff0011",
      catalog_path: "/catalog/KIT-SHIFT-05",
      public_report_summary: "Published County Food-Safety Cold/Hot Holding Reference Table.",
    },
  },
};

function buildQueuedRequestStatus(requestId) {
  return {
    synthetic: true,
    request_id: requestId,
    kit_id: "KIT-TRANSCR-07",
    kit_title: "Pending Scope & Kit Assignment",
    status: "queued",
    submitted_at: "2026-10-31T19:00:00Z",
    organization_type: "Nonprofit requester session",
    plain_need:
      "Submitted nonprofit request filed onto Tessera queue eq01 (scope and sort-and-split). Waiting for an authorized volunteer worker to claim.",
    privacy_guarantee:
      "Requests hold only plain-words job descriptions and public links. Private files stay with your organization.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "queued-on-tessera-eq01",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: ["Any step touching internal folders or records becomes a local kit"],
        outcome_title: "Local agent kit (queued)",
        outcome_detail: "A volunteer's agent will draft and test a kit you run locally.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["Publicly published budgets, statutes, or directories"],
        outcome_title: "Cited public research (queued)",
        checks: [
          "Every claim cited to public sources",
          "Reviewed by a second volunteer's agent",
          "Your staff decide how to use it",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "waiting-for-volunteer-claim",
      harness: "Any connected MCP / Herma worker",
      lease_minutes: 30,
      fencing_token: 0,
      claim_receipt: "awaiting-claim",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "connection", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "awaiting-build",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "builder-guard",
        role: "policy gate",
        http_status: 409,
        reason: "Active: the builder will be blocked from approving its own kit.",
        receipt: "enforced-by-tessera",
      },
      reviewer_approval: {
        actor: "awaiting-second-volunteer",
        role: "independent reviewer",
        harness: "Second donor worker",
        checks_passed: 8,
        summary:
          "A second volunteer's agent must independently verify all 8 deterministic checks before catalog publication.",
        receipt: "awaiting-review",
      },
      cli_transcript: [
        `› tessera get_task ${requestId} --queue eq01`,
        "  status: ready · waiting for volunteer worker claim (claim · do · report)",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: false,
      steward_id: "pending-steward",
      steward_note: "Sensitive kits wait for human steward sign-off before publication.",
      steward_receipt: "pending",
      catalog_path: "/catalog/KIT-TRANSCR-07",
      public_report_summary: "Example completed flow available at /requests/REQ-INTAKE-07.",
    },
  };
}

function lookupRequestStatus(requestId) {
  if (Object.prototype.hasOwnProperty.call(SHOWCASE_REQUEST_STATUS, requestId)) {
    return SHOWCASE_REQUEST_STATUS[requestId];
  }
  if (/^rq-[a-z0-9-]{4,80}$/.test(requestId)) {
    return buildQueuedRequestStatus(requestId);
  }
  return null;
}

function isMissingRequestPage(pathname) {
  const path = pathname.replace(/\/+$/, "");
  if (!APP_REQUEST_PAGE_RE.test(path)) return false;
  const reqId = decodeSegment(path.slice("/requests/".length));
  if (reqId === BROKEN_ESCAPE || !REQUEST_STATUS_ID_RE.test(reqId)) return true;
  return !lookupRequestStatus(reqId);
}

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
  return new Response(request.method === "HEAD" ? null : html, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

// Public Eranos nouns (page text, plans, requests, delivered reports, sources, verb templates):
// Tessera's mirror first, then the snapshot exported from Tessera with this deploy.
const PUBLIC_NOUN_STORES = new Set(["eranos.instructions", "eranos.plans", "eranos.requests", "eranos.solutions", "eranos.sources", "eranos.verb_templates"]);
const NOUN_KEY_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

async function loadNoun(request, env, store, key) {
  const stored = await getHeadRecord(env.FABRIC_DB, store, key);
  if (stored !== null && stored !== undefined) return { synthetic: true, store, key, value: stored };
  const snap = await fetchAssetJson(request, env, `/snapshot/nouns/${store}/${key}.json`);
  return snap && snap.store === store && snap.key === key ? snap : null;
}

async function loadNounList(request, env, store) {
  if (env && env.FABRIC_DB) {
    const res = await env.FABRIC_DB.prepare(
      "SELECT h.key AS key, h.version AS version, r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.namespace = 'main' AND r.namespace = h.namespace AND h.producer_surface = 'surface:eranos' AND r.producer_surface = h.producer_surface AND h.visibility_scope = 'public_commons' AND r.visibility_scope = 'public_commons' AND NOT EXISTS (SELECT 1 FROM json_each(h.tags) WHERE value = 'status:quarantined') AND NOT EXISTS (SELECT 1 FROM json_each(r.tags) WHERE value = 'status:quarantined') ORDER BY h.key LIMIT 100"
    ).bind(store).all();
    const records = (res.results || []).map((r) => ({ key: r.key, version: Number(r.version), value: JSON.parse(r.value) }));
    if (records.length) return { synthetic: true, store, records };
  }
  const snap = await fetchAssetJson(request, env, `/snapshot/nouns/${store}.json`);
  return snap && snap.store === store && Array.isArray(snap.records) ? snap : { synthetic: true, store, records: [] };
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
    return jsonResp(await withDraftDigest(result, body));
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
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

  if (pathname === "/api/examples") {
    // Example needs and recorded example runs are repository nouns, built into this deploy's snapshot.
    const examples = await fetchAssetJson(request, env, "/snapshot/examples.json");
    if (!examples) {
      return problem(404, "Not Found", "this build has no example nouns", "not_found");
    }
    return jsonResp(examples);
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
    if (key === null) return jsonResp(await loadNounList(request, env, store));
    const found = await loadNoun(request, env, store, key);
    return found ? jsonResp(found) : problem(404, "Not Found", "no such public noun", "not_found");
  }

  if (pathname === "/api/requests") {
    return jsonResp(await loadRequestsPayload(request, env));
  }

  const reqStatusMatch = /^\/api\/requests\/([^/]+)$/.exec(pathname);
  if (reqStatusMatch) {
    const reqId = decodeSegment(reqStatusMatch[1]);
    if (reqId === BROKEN_ESCAPE || !REQUEST_STATUS_ID_RE.test(reqId)) {
      return problem(400, "Bad Request", "invalid request id", "invalid_request");
    }
    const foundReq = lookupRequestStatus(reqId);
    if (!foundReq) {
      return problem(404, "Not Found", `request ${reqId} is not found`, "not_found");
    }
    return jsonResp(foundReq);
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
            (await isMissingKitPage(request, env, pathname)) ||
            isMissingRequestPage(pathname))
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
