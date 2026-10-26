# Hosting Eranos

Eranos runs behind a Cloudflare Worker (`eranos`) in front of one small Fly.io API container
(`eranos-api`) with a persistent 1 GB volume (`eranos_data`) for its local SQLite store and traces.

Under the shared single-domain layout, all three public-good surfaces share one root domain on free
Cloudflare Workers Custom Domains:

| Subdomain | Worker | Origin | Purpose |
|---|---|---|---|
| `shamash.<domain>` | `shamash` | `shamash-api.fly.dev` | Fraud & exploitation detection |
| `eranos.<domain>` | `eranos` | `eranos-api.fly.dev` | Nonprofit & NGO volunteer agent tooling |
| `tessera.<domain>` | `tessera` | `tessera-api.fly.dev` | Shared atomic queue, CAS records & blob store |

Until a custom domain is bound, `eranos.<account>.workers.dev` serves the exact same Worker and `/api/*`
proxy with zero extra cost.

## Files

- [`hosting.env`](hosting.env) — non-secret app, Worker, volume, health URL, and optional `CUSTOM_DOMAIN`
- [`bootstrap-hosting.sh`](bootstrap-hosting.sh) — shared dry-run-capable bootstrap script
- [`cloudflare/`](cloudflare/README.md) — Cloudflare Worker (`worker.js` + `wrangler.jsonc`)
- [`fly/`](fly/README.md) — Fly.io container (`Dockerfile`, `Dockerfile.dockerignore`, `fly.toml`)
