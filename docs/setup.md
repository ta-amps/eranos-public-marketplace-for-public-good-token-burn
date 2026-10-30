# Setup and Single-Domain Hosting

## Local setup (no cloud accounts needed)

```bash
git clone https://github.com/ta-amps/eranos.git
cd eranos
make setup
make check
make verify-examples
make snapshot
make web
```

Port defaults avoid busy ports (`8000`–`8003`, `8787`, `18080`):
- **Tessera** local service & edge: `127.0.0.1:7700` / `127.0.0.1:7701`
- **Eranos** local API & Vite app: `127.0.0.1:7720` / `localhost:5174`

Tessera installs automatically from the immutable Git revision in `pyproject.toml` and `uv.lock`.
A sibling checkout is needed only for the optional `make suite` conformance target or for running a
separate local Tessera server.

## Donating unused tokens with your AI agent

1. Start Tessera locally (`cd ../tessera && make dev && make seed`) or point `TESSERA_URL` at the hosted
   Tessera edge.
2. Issue one scoped key per contributor's agent (`--queue eq02` to build & test drafts, or `--queue eq03` to
   independently test & review someone else's draft; `--scope store`, never `public`).
3. Seed open NGO build briefs with `uv run eranos seed-requests`.
4. Point your coding agent's leftover tokens at Tessera via MCP (`/mcp`), HTTP (`/v1/tasks/claim`), CLI, or
   browser forms (`/work`).

## Single-domain subdomain hosting

Eranos is one of exactly two public surfaces (Agora, the single overview, is the other); Tessera and Herma are
infrastructure; everything else is nouns and verbs in seed packs. To keep domain costs to **one** registration,
Eranos and Tessera share one root domain in Cloudflare via Worker Custom Domains (free DNS + TLS per subdomain):

- `eranos.<your-domain>` → Eranos Cloudflare Worker → `eranos-api.fly.dev`
- `tessera.<your-domain>` → Tessera Cloudflare Worker → `tessera-fabric.fly.dev`

Run `deploy/bootstrap-hosting.sh --dry-run` first to inspect the exact plan without printing any secret or
deploying anything.
