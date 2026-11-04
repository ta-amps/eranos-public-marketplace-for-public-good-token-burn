# B4 go-live: prepared, not executed

Nothing below has been sent. Each step names the owner decision it needs. The owner's decisions
(`functional/OWNER-DECISIONS.md`, Oct 31) allow these hosted writes after an independent review, using
the limited keys B1 issues and the Herma admin sync. Keys live only in 0600 env files and are never
printed. `scripts/golive.py execute` reads them from `TESSERA_KEY_FILE` (line `TESSERA_KEY=...`) and
`HERMA_ADMIN_KEY_FILE` (line `HERMA_ADMIN_KEY=...`). Every response is appended to
`golive/<pack>/receipts.jsonl` (the HTTP status and the first 300 characters, never a key). A failed
step stays on the record.

The live path goes through B1's worker loop. Its workers build, store and publish the package
themselves, so only Herma's sync is a separate step here.

| # | Step | Command | Owner decision it needs |
|---|---|---|---|
| 1 | Local checks | `python3 -m unittest discover -s tests -v` (14), `(cd runner && python3 -m unittest discover -s tests -v)` (9), `python3 scripts/build.py requests/first-process.json` (8 of 8 checks, including the clean-folder container test) | none ($0, local) |
| 2 | The lead's independent review of this build and of branch `b4-process-handler` (off `worker-loop`) | the lead reads and re-runs. For a re-run of the package: `python3 scripts/review.py --build out/process-sheet-cleaning-7eefca.build.json --reviewer-id <id> --reviewer-key-id <key id>` (refuses the builder) | the lead's review |
| 3 | Install the handler in the live workers | merge `b4-process-handler`, then start B1's builder and reviewer units with `ERANOS_PROCESS_HANDLER=<this folder>/eranos_handler.py` and `ERANOS_SEED_PACKS=<library clone>`, and the reviewer also with `ERANOS_PROCESS_BUILDER_KEYS=<the dedicated builder key id>` (required: the reviewer refuses to start without it) | D1 and D6 (live workers, background services) |
| 4 | The film's request, live | the owner submits "A reusable process to clean our volunteer sign-up spreadsheets: remove duplicates, fix date and phone formats, flag missing contact fields, with a short report." (output type process, one-off) through the redesigned marketplace. B1's planner claims it. Its builder runs `build_process` (fixed templates, no model; container test) and stores the bundle as a Tessera blob, whose SHA-256 is its identity. It writes request-scoped drafts `eranos.processes/<request>.1.PRC-7EEFCA-01` and `eranos.process_templates/<request>.1.process-sheet-cleaning-7eefca` quarantined. A different key derives those keys from the request, fetches the blob by digest, runs `review_process`, publishes both and lists `eranos.catalog/PRC-7EEFCA-01` with its review receipt and `publication_sha256` (Tessera's publication guard) | D2 (one public request), D1 keys |
| 5 | A public download URL | Tessera blobs and bucket objects are not readable without a key (finding F31-B4-05). The redesigned marketplace serves `GET /api/packages/<pack>.tar.gz`, streaming the blob with its own read key plus an `x-content-sha256` header, or the bundle ships as a static file | D3 (deploy after review); B1 and B2 build the route |
| 6 | Herma finds it | `python3 scripts/golive.py herma-prepare --build out/runs/<request id>.1/process-sheet-cleaning-7eefca.build.json --catalog-key PRC-7EEFCA-01 --template-key <request id>.1.process-sheet-cleaning-7eefca`, then `TESSERA_KEY_FILE=<0600> python3 scripts/golive.py execute --build <same> --step herma-records` (2 context entries, their index and `PROV-DATA-CLEANING-PIPELINE` go into a store of their own, `herma.provisions.process-packages[.context]`, so the sync never re-imports the stale `herma.provisions` records of F-142). Then `HERMA_ADMIN_KEY_FILE=<0600> TESSERA_KEY_FILE=<0600> python3 scripts/golive.py execute --build <same> --step herma-sync` (POST `/v1/sync/tessera` with `builtin: true`, then the public `/api/preview` with the film's prompt) | D1 hosted writes; the Herma admin credential |
| 7 | The reworded request | the owner (or a second organization) asks for the same pipeline in other words. The planner's keyed reuse finds `reuse:proc2-7eefca618400649c` in the reviewed catalog entry and delivers it as a pointer with a `reused` receipt: 0 new verbs, 0 model tokens | D2 (a public request; counts within the three) |

Not on the live path: `golive.py prepare` and `execute --step bucket|records` upload the locally built
bundle to a bucket and write the records directly. Use them only if B1's loop is not used.

## What each step proves (B4 acceptance)

- (a) Steps 4 and 5: the package downloads from a public URL and its SHA-256 matches `value.blob_sha256` of the catalog entry.
- (b) Steps 1, 2 and 4: `docker compose run --rm test` passes offline from a clean folder, in the build and again in the review.
- (c) Step 1 and `evidence/harness-runs.md`: 8 harness configs pass the persona compiler's checks; Claude Code and OpenCode load them on a local model.
- (d) Step 4: `build_packs.py --instantiate` makes a valid TaskSpec (the `instantiate` check). The pieces' claimant and the reviewer key are on the record, and the review refuses the builder's key.
- (e) Steps 4 and 5: catalog search for "data cleaning" returns the entry. Its summary says "data-cleaning pipeline".
- (f) Step 6: Herma's preview lists `PROV-DATA-CLEANING-PIPELINE` and the catalog noun among its shimmed context refs.
- (g) Step 7: the reworded request is answered from the stored package with 0 new eq02/eq03 verbs and 0 model tokens.
