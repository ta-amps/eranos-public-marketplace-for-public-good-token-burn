# Cloudflare: the Eranos edge

One Worker named `eranos` serves the built React 19 web app (`web/dist`) and proxies `/api/*` to the
Eranos API on Fly.io (`API_ORIGIN`, default `https://eranos-api.fly.dev`):

- every non-`/api` path serves static assets from `web/dist` (falling back to `index.html` for SPA routes);
- `/api/*` forwards to `API_ORIGIN` with `x-edge-auth`, `x-forwarded-host`, and `x-forwarded-proto` added,
  hop-by-hop headers and cookies stripped, and `Cache-Control: no-store` on API responses;
- every response carries HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy: camera=(), microphone=(), geolocation=()`, `X-Frame-Options: DENY`, and a strict
  same-origin Content Security Policy.

## Shared single-domain custom subdomain

To bind `eranos.<your-domain>` alongside `shamash.<your-domain>` and `tessera.<your-domain>` on a single
Cloudflare zone:

1. Uncomment `"routes"` in [`wrangler.jsonc`](wrangler.jsonc) and set `"pattern": "eranos.<your-domain>"`.
2. Set `CUSTOM_DOMAIN="eranos.<your-domain>"` and `HEALTH_URL="https://eranos.<your-domain>/api/health"` in
   [`../hosting.env`](../hosting.env).
3. Deploy via the GitHub `deploy` workflow (requires approval in the `production` environment).

## Origin lockdown

`EDGE_SECRET` on the Worker and `ERANOS_EDGE_SECRET` on the Fly.io app hold the same random 32-byte hex
secret set by `deploy/bootstrap-hosting.sh`. Direct requests to `eranos-api.fly.dev` without matching
`x-edge-auth` receive HTTP 403, except `GET /api/health` for Fly health checks.

## Theme and CSP

The web entry point imports the Astryx neutral `built` theme and `theme.css`. Theme CSS and layout
styles are served as static assets; runtime style injection is disabled. Keep `style-src 'self'` and
move layout changes into CSS classes. `web/tests/csp.spec.ts` runs the production bundle under this
Worker's CSP at desktop and mobile sizes and checks applied theme tokens, violations, and overflow.
