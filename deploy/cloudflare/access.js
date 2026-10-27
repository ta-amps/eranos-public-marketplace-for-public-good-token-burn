// Public browser-agent access uses bearer headers, never cookies.
export const FABRIC_CONNECT = "https://tessera.ta-amps.workers.dev/connect";
export const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, POST, OPTIONS",
  "access-control-allow-headers": "Authorization, Content-Type, If-Match, X-Request-Id, X-Agent-Label",
  "access-control-expose-headers": "ETag, Retry-After, X-Request-Id",
  "access-control-max-age": "600",
};
export function accessDescriptor(surface) {
  return {
    surface, fabric_connect_url: FABRIC_CONNECT, mcp_url: `https://${surface}.ta-amps.workers.dev/mcp`,
    authentication: "Public reads and practice require no key. Tracked noun/verb work uses a Tessera anonymous session or API key.",
    surface_persistence: false, cookies: false,
    anonymous: {session_endpoint: "https://tessera.ta-amps.workers.dev/v1/session/anonymous", token_prefix: "tan_", scope: "isolated demo namespace; quotas and expiry returned at mint"},
    keyed: {token_prefix: "tsk_", connect_url: FABRIC_CONNECT, scope: "account and key grants; operator approval for production writes"},
    practice: surface === "eranos" ? {endpoint: "/api/practice", persisted: false} : null,
    restrictions: surface === "shamash" ? "Public ingestion is disabled. Public examples are SYNTHETIC only." : "Practice never persists or publishes kits. Donations and publication require scoped Tessera keys.",
  };
}
export function accessResponse(request, surface) {
  const path = new URL(request.url).pathname;
  if (request.method === "OPTIONS") return new Response(null, {status: 204, headers: CORS_HEADERS});
  if (path !== "/connect" && path !== "/connect.json") return null;
  if (!["GET", "HEAD"].includes(request.method)) return new Response("Method Not Allowed", {status: 405});
  const info = accessDescriptor(surface);
  if (path.endsWith(".json")) return Response.json(info);
  return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect to ${surface}</title><body><main><h1>Connect to ${surface}</h1><p>${info.authentication}</p><p>${info.restrictions}</p><p><a href="${FABRIC_CONNECT}">Get an anonymous demo session</a></p><p><a href="${FABRIC_CONNECT}">Create or use an API key</a></p><p>Anonymous work has immutable demo and untrusted labels, a private demo namespace, quotas and an expiry shown when the session is created.</p><p>Use Authorization: Bearer YOUR_TOKEN with the Tessera MCP endpoint. No token is required for this surface's public tools.</p><a href="/connect.json">Machine-readable access modes</a> <a href="/">Home</a></main></body></html>`,{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
}
