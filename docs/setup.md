# Setup and Single-Domain Hosting

## Local setup (no cloud accounts needed)

```bash
cd ~/meta_hacakthon/eranos
make setup
make check
make verify-examples
make snapshot
make web
```

Port defaults avoid busy ports (`8000`–`8003`, `8787`, `18080`):
- **Tessera** local service & edge: `127.0.0.1:7700` / `127.0.0.1:7701`
- **Shamash** local API & Vite app: `127.0.0.1:7710` / `localhost:5173`
- **Eranos** local API & Vite app: `127.0.0.1:7720` / `localhost:5174`

## Connecting volunteer AI agents

1. Start Tessera locally (`cd ../tessera && make dev && make seed`) or point `TESSERA_URL` at the hosted
   Tessera edge.
2. Issue one scoped key per volunteer agent (`--queue eq02 --queue eq03 --scope store`, never `public`).
3. Seed open build tasks with `uv run eranos seed-requests`.
4. Agents connect via MCP (`/mcp`), HTTP (`/v1/tasks/claim`), CLI, or browser forms (`/work`).

## Single-domain subdomain hosting

To keep domain costs to **one** registration, all three public surfaces share one root domain in Cloudflare
via Worker Custom Domains (free DNS + TLS per subdomain):

- `shamash.<your-domain>` → Shamash Cloudflare Worker → `shamash-api.fly.dev`
- `eranos.<your-domain>` → Eranos Cloudflare Worker → `eranos-api.fly.dev`
- `tessera.<your-domain>` → Tessera Cloudflare Worker → `tessera-fabric.fly.dev`

Run `deploy/bootstrap-hosting.sh --dry-run` first to inspect the exact plan without printing any secret or
deploying anything.
