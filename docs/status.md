# Status

Updated by hand. Last update: **October 30, 2026**. This page does not refresh itself, so check the date before
you rely on it.

## On your computer

Checked on October 29, 2026, in a fresh clone of `main` with this page's documentation change.

| Command | Result |
|---|---|
| `make check` | Lint, strict types, secret scan, index and architecture checks pass; 79 tests passed and 1 skipped. The skipped test compares shared scripts with a `hackathon-context` checkout next to this one, and passes when that checkout is present |
| `make verify-examples` | Every example kit is built, checked, independently reviewed and published to a local catalog. Kits that point at a seed pack are composed from the library first. Sensitive kits wait for a steward's sign-off and then resume |
| `make record-runs` | Every example kit is checked, built and independently reviewed with this repository's own pipeline on a throwaway local store, and one evidence noun per kit is written to `examples/runs/`. These are example runs on one computer with synthetic data, not hosted volunteer runs |
| `make suite BACKEND=local` | Teleion Fabric's conformance suite through Eranos's adapter: 30 passed, 6 skipped, using Teleion Fabric revision that CI uses |

## Open contribution and the nonprofit side, October 30, 2026

On branch `t/e2e-open-contribution-20261030`, not merged or deployed:

- `make e2e` passes locally against an in-process Teleion Fabric at the pinned revision: sign-up, browsing, one
  request verb per typed request, classify and split for public-only, private-files and mixed requests,
  anonymous work, quarantine, review by a different keyed worker, a person's sign-off on a sensitive kit,
  delivery into the nonprofit's namespace and records. The abuse checks hold.
- The hosted sites do not have this yet. It needs Teleion Fabric release with open verbs and requester keys,
  the Eranos Worker, and the page-text nouns seeded with `eranos seed-nouns`. Until then the pages fall back to
  the nouns exported with the build, and the request box answers only on a deployed stack.
- The classify, build and research steps in `make e2e` are deterministic stand-ins for the reasoning a
  volunteer's own agent does. They show the contract, not the quality of real work.

## Hosted site

The hosted site at `https://eranosforgood.org` needs Teleion Fabric for tasks, queue counts and publishing
kits.

- On October 29, 2026, hosted Teleion Fabric reached Cloudflare's free daily limit on storage writes and stopped
  accepting work for part of the day.
- Later that day, at 18:36 UTC, a live check of Teleion Fabric's main operations passed: health, agent card, anonymous
  session, claim, heartbeat and submit. That check covered Teleion Fabric, not the Eranos site.
- If Teleion Fabric runs out of storage allowance again, it answers with HTTP 503, the code `storage_quota_exhausted`,
  a `Retry-After` header and the reset time. Wait until then instead of retrying in a loop.
- Eranos's own `/healthz` and `/api/health` describe only the Eranos worker. They answer `ok` even when Teleion Fabric
  is unavailable, so they are not a full health check.

Agora, the single overview and the other public surface besides Eranos, records dated status across all of the
repositories. Teleion Fabric and the Teleion Fabric shim are infrastructure; everything else is nouns and verbs in seed packs.

## Known limits

- Every example and test uses synthetic data. A reviewed kit is not certified for any particular organization.
- The hosted site never calls an AI model. The optional donor demo calls one only when an operator asks for it,
  and that path has no shared spending reservation or global budget yet.
- A practice record hashes the check's outcome, not the exact draft text. Exact-content records are a
  follow-up; see the [agent workflow](agent-workflow.md).

## Updating this page

Re-run the commands above, then record the date, the revision and every failure or unknown. A local test never
shows that the hosted site is up.
