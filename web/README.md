# Eranos Web App (`web/`)

React 19, TypeScript (strict), Vite, and Astryx interface for Eranos.

## Local development

- Dev server (`:5174`, proxying `/api` to `http://127.0.0.1:7720`): `make web` from the repo root
- Strict type-check & production build: `make web-check`
- Export offline snapshot from the two-step Tessera pipeline: `make snapshot`
- Offline snapshot build (`VITE_SNAPSHOT=1`): `pnpm --dir web snapshot:build`
