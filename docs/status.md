# Status

Updated by hand. Last update: **October 29, 2026**. This page does not refresh itself, so check the date before
you rely on it.

## On your computer

Checked on October 29, 2026, in a fresh clone of `main` with this page's documentation change.

| Command | Result |
|---|---|
| `make check` | Lint, strict types, secret scan, index and architecture checks pass; 55 tests passed and 1 skipped. The skipped test compares shared scripts with a `hackathon-context` checkout next to this one, and passes when that checkout is present |
| `make verify-examples` | All five example kits are built, checked, independently reviewed and published to a local catalog. One sensitive kit waits for a steward's sign-off and then resumes |
| `make suite BACKEND=local` | Tessera's conformance suite through Eranos's adapter: 30 passed, 6 skipped, using the Tessera revision that CI uses |

## Hosted site

The hosted site at `https://eranos.ta-amps.workers.dev` needs Tessera for tasks, queue counts and publishing
kits.

- On October 29, 2026, hosted Tessera reached Cloudflare's free daily limit on storage writes and stopped
  accepting work for part of the day.
- Later that day, at 18:36 UTC, a live check of Tessera's main operations passed: health, agent card, anonymous
  session, claim, heartbeat and submit. That check covered Tessera, not the Eranos site.
- If Tessera runs out of storage allowance again, it answers with HTTP 503, the code `storage_quota_exhausted`,
  a `Retry-After` header and the reset time. Wait until then instead of retrying in a loop.
- Eranos's own `/healthz` and `/api/health` describe only the Eranos worker. They answer `ok` even when Tessera
  is unavailable, so they are not a full health check.

Agora, the single overview and the other public surface besides Eranos, records dated status across all of the
repositories. Tessera and Herma are infrastructure; everything else is nouns and verbs in seed packs.

## Known limits

- Every example and test uses synthetic data. A reviewed kit is not certified for any particular organization.
- The hosted site never calls an AI model. The optional donor demo calls one only when an operator asks for it,
  and that path has no shared spending reservation or global budget yet.
- A practice receipt hashes the check's outcome, not the exact draft text. Exact-content receipts are a
  follow-up; see the [agent workflow](agent-workflow.md).

## Updating this page

Re-run the commands above, then record the date, the revision and every failure or unknown. A local test never
shows that the hosted site is up.
