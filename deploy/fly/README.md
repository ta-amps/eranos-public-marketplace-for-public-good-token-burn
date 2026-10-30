# Fly.io: the Eranos API

One small shared-CPU machine (`eranos-api`) with a 1 GB volume (`eranos_data`) for the local SQLite store
and JSONL traces. It sits behind the `eranos` Cloudflare Worker, which injects `x-edge-auth`; when
`ERANOS_EDGE_SECRET` is set, the API returns HTTP 403 to direct requests except `GET /api/health`.

## Secrets

Secrets live only in Fly (`fly secrets import` via stdin in `deploy/bootstrap-hosting.sh`):
`ERANOS_EDGE_SECRET`, and optionally `TESSERA_KEY` / `MODEL_API_KEY` when connected to a remote Tessera
service or Meta Model API in Standard mode. Never commit secrets or pass them on a command line.

## First-time setup & deploy

Deploys require Taylor's approval each time.

1. Run `deploy/bootstrap-hosting.sh --dry-run` first, then `deploy/bootstrap-hosting.sh` under the
   `ta-amps` Fly, Cloudflare, and GitHub accounts.
2. Preferred deploy path: trigger the GitHub `deploy` workflow (`api` or `both`), which waits for
   approval in the `production` environment, checks out Eranos and installs the pinned Tessera dependency, copies
   `Dockerfile.dockerignore` to `.dockerignore`, and runs `flyctl deploy --remote-only`.
3. Clean-directory manual deploy (never run `fly deploy` from a parent folder containing private notes):

```bash
mkdir /tmp/eranos-deploy && cd /tmp/eranos-deploy
git clone https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn.git eranos
cp eranos/deploy/fly/Dockerfile.dockerignore .dockerignore
fly deploy . --config eranos/deploy/fly/fly.toml --dockerfile eranos/deploy/fly/Dockerfile --remote-only
```
