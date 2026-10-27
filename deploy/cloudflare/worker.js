// Cloudflare Cloud Worker for Eranos. Serves the web app's static files (SPA fallback) and
// serves `/api/*` natively 24/7 from Cloudflare D1 (`ta-amps-fabric`, mirrored live from Tessera Cloud)
// + `env.TESSERA` Service Binding (`STORAGE_MODE = "cloud"`), with optional Fly.io origin fallback.

const DEFAULT_API_ORIGIN = "https://eranos-api.fly.dev";
const ERANOS_VERSION = "0.1.0";
const KIT_ID_RE = /^KIT-[A-Z0-9][A-Z0-9-]{1,46}$/;
const ERANOS_QUEUES = new Set(["eq01", "eq02", "eq03"]);

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
  const out = new Response(response.body, response);
  stripHopByHop(out.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) out.headers.set(name, value);
  if (method !== "GET" && method !== "HEAD") out.headers.set("cache-control", "no-store");
  return out;
}

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}

function problem(status, title, detail, code = "invalid_request") {
  return new Response(JSON.stringify({ type: "about:blank", title, status, detail, code }), {
    status,
    headers: { "content-type": "application/problem+json", "cache-control": "no-store" },
  });
}

async function getHeadRecord(db, store, key) {
  if (!db) return null;
  const row = await db
    .prepare(
      "SELECT r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? AND h.key = ?"
    )
    .bind(store, key)
    .first();
  return row ? JSON.parse(row.value) : null;
}

async function listHeadRecords(db, store) {
  if (!db) return [];
  const res = await db
    .prepare(
      "SELECT r.value AS value FROM record_heads h JOIN records r ON r.store = h.store AND r.key = h.key AND r.version = h.version WHERE h.store = ? ORDER BY h.key"
    )
    .bind(store)
    .all();
  return (res.results || []).map((r) => JSON.parse(r.value));
}

async function handleCloudApi(request, env, pathname) {
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

  if (pathname === "/api/tracks") {
    const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "tracks");
    if (stored) return jsonResp(stored);
    return await env.ASSETS.fetch(new URL("/snapshot/tracks.json", request.url));
  }

  if (pathname === "/api/requests") {
    const stored = await getHeadRecord(env.FABRIC_DB, "eranos.meta", "requests");
    if (stored) return jsonResp(stored);
    return await env.ASSETS.fetch(new URL("/snapshot/requests.json", request.url));
  }

  if (pathname === "/api/catalog") {
    const kits = await listHeadRecords(env.FABRIC_DB, "eranos.catalog");
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
    const found = await getHeadRecord(env.FABRIC_DB, "eranos.catalog", kitId);
    if (!found) {
      return problem(404, "Not Found", `kit ${kitId} is not in the catalog`, "not_found");
    }
    return jsonResp({ synthetic: true, ...found });
  }

  if (pathname === "/api/fabric") {
    let queues = [];
    if (env.TESSERA) {
      try {
        const resp = await env.TESSERA.fetch("https://tessera.ta-amps.workers.dev/v1/health");
        if (resp.ok) {
          const h = await resp.json();
          queues = (h.queues || [])
            .filter((q) => ERANOS_QUEUES.has(q.name))
            .map((q) => ({ name: q.name, ...q.counts }));
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

  return problem(404, "Not Found", `No API route matches ${pathname}`, "not_found");
}

async function proxyApi(request, env) {
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

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    let response;
    if (pathname === "/api" || pathname.startsWith("/api/")) {
      if ((env.STORAGE_MODE || "cloud") === "origin") {
        response = await proxyApi(request, env);
      } else {
        response = await handleCloudApi(request, env, pathname);
      }
    } else if (request.method === "GET" || request.method === "HEAD") {
      response = await env.ASSETS.fetch(request);
    } else {
      response = new Response("Method Not Allowed", { status: 405, headers: { allow: "GET, HEAD" } });
    }
    return finish(response, request.method);
  },
};
