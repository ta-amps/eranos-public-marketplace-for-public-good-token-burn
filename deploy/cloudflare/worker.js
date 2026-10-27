// Cloudflare Cloud Worker for Eranos. Serves the web app's static files (SPA fallback) and
// serves `/api/*` natively 24/7 from Cloudflare D1 (`ta-amps-fabric`, mirrored live from Tessera Cloud)
// + `env.TESSERA` Service Binding (`STORAGE_MODE = "cloud"`), with optional Fly.io origin fallback.

const DEFAULT_API_ORIGIN = "https://eranos-api.fly.dev";
const ERANOS_VERSION = "0.1.0";
const KIT_ID_RE = /^KIT-[A-Z0-9][A-Z0-9-]{1,46}$/;
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
            return jsonResp({ synthetic: true, ...payload });
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
