// Public browser-agent access uses bearer headers, never cookies.
export const FABRIC_CONNECT = "https://tessera.teleionlabs.com/connect";
export const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, POST, OPTIONS",
  "access-control-allow-headers": "Authorization, Content-Type, If-Match, X-Request-Id, X-Agent-Label",
  "access-control-expose-headers": "ETag, Retry-After, X-Request-Id",
  "access-control-max-age": "600",
};
export function accessDescriptor(surface) {
  return {
    surface, fabric_connect_url: FABRIC_CONNECT, mcp_url: surface === "eranos" ? "https://eranosforgood.org/mcp" : `https://${surface}.ta-amps.workers.dev/mcp`,
    authentication: "Public reads and practice need no key. Tracked work on Tasks uses a Tessera anonymous session or an API key.",
    surface_persistence: false, cookies: false,
    anonymous: {session_endpoint: "https://tessera.teleionlabs.com/v1/session/anonymous", token_prefix: "tan_", scope: "isolated demo namespace; quotas and expiry returned at mint"},
    keyed: {token_prefix: "tsk_", connect_url: FABRIC_CONNECT, scope: "account and key grants; operator approval for production writes"},
    practice: surface === "eranos" ? {endpoint: "/api/practice", persisted: false} : null,
    restrictions: "Practice never persists or publishes kits. Donations and publication require scoped Tessera keys.",
  };
}
export function accessResponse(request, surface) {
  const path = new URL(request.url).pathname;
  if (request.method === "OPTIONS") return new Response(null, {status: 204, headers: CORS_HEADERS});
  if (path !== "/connect" && path !== "/connect.json") return null;
  if (!["GET", "HEAD"].includes(request.method)) return new Response("Method Not Allowed", {status: 405, headers: {allow: "GET, HEAD"}});
  const info = accessDescriptor(surface);
  if (path.endsWith(".json")) return Response.json(info, {headers: {"cache-control": "private, no-store"}});
  return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect to ${surface}</title><body><main><h1>Connect to ${surface}</h1><p>${info.authentication}</p><p>${info.restrictions}</p><p><a href="${FABRIC_CONNECT}">Get an anonymous demo session</a></p><p><a href="${FABRIC_CONNECT}">Create or use an API key</a></p><p>Anonymous work has immutable demo and untrusted labels, a private demo namespace, quotas and an expiry shown when the session is created.</p><p>Use Authorization: Bearer YOUR_TOKEN with the Tessera MCP endpoint. No token is required for this surface's public tools.</p><a href="/connect.json">Machine-readable access modes</a> <a href="/">Home</a></main></body></html>`,{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
}

// Public callers never inherit a service binding's private or cohort authority.
export function publicFeedPayload(payload, after = 0) {
  const out = { synthetic: true, feed: "noun.promotions", entries: [], next_cursor: after };
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || payload.feed !== "noun.promotions" || !Array.isArray(payload.entries)) {
    return { ...out, degraded: true, reason: "invalid upstream feed response" };
  }
  const cursor = value => Number.isSafeInteger(value) && value >= 0;
  const surface = value => typeof value === "string" && /^surface:[a-z0-9][a-z0-9_-]{1,39}$/.test(value);
  const fields = ["seq", "feed", "kind", "summary", "payload", "created_at", "namespace", "producer_surface", "visibility_scope", "allowed_surfaces", "target_cohorts", "tags"];
  if (cursor(payload.next_cursor)) out.next_cursor = Math.max(after, payload.next_cursor);
  for (const entry of payload.entries) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry) || !cursor(entry.seq)) continue;
    out.next_cursor = Math.max(out.next_cursor, entry.seq);
    if (entry.seq <= after || entry.namespace !== "main" || entry.visibility_scope !== "public_commons"
      || !surface(entry.producer_surface)
      || !Array.isArray(entry.tags) || !entry.tags.every(tag => typeof tag === "string")
      || !entry.tags.includes("status:verified")
      || entry.tags.some(tag => tag.trim().toLowerCase() === "status:quarantined")
      || !Array.isArray(entry.allowed_surfaces) || !entry.allowed_surfaces.every(surface)
      || !Array.isArray(entry.target_cohorts) || !entry.target_cohorts.every(cohort => typeof cohort === "string")
      || !entry.target_cohorts.includes("all")) continue;
    out.entries.push(Object.fromEntries(fields.filter(key => Object.hasOwn(entry, key)).map(key => [key, entry[key]])));
  }
  return out;
}
