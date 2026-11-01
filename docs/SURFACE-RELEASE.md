# Preserve the current surface on every release

Eranos uses a light-only interface, including when the visitor's operating system
prefers dark colors. Request pages keep the four collapsible steps and keyboard
controls. Dark ink, icons and buttons are valid; a second dark page palette is
not. These are release invariants, alongside the current backend fixes.

A backend branch must include the reviewed UI ancestry in
`deploy/cloudflare/surface-release-policy.json`. Merge the branches and resolve
behavioral conflicts; do not deploy a stale frontend build with a newer backend.
The required commits preserve the approved interface and the later track
readiness, explicit refusal reasons and read-after-write changes.

1. Read the shared deployment handoff and record the currently live Cloudflare
   version. Coordinate one release owner and pause other deployments.
2. Run `make check`, then `ERANOS_TEST_PORT=4274 pnpm --dir web exec playwright
   test --workers=2`. Both ports 4274 and 4275 must be free. Existing servers are
   never reused. Snapshot tests build into `dist-snapshot`, separate from the
   production `dist`. Browser checks cover both OS color preferences, actual
   computed colors and request accordion interactions; screenshots are retained
   in `web/test-results`.
3. Commit the reviewed source. Run `python3 scripts/check_surface_release.py
   --prepare --expected-live-version <observed-version>`. This creates a fresh
   production build with snapshot mode explicitly disabled, including when a
   local dotenv file enables it. It pins every asset to the exact source commit.
4. Have a different reviewer inspect source, test results and the generated
   `web/dist/surface-release.json`. Immediately before deployment, the release
   operator must query Cloudflare again and stop if its live version changed.
   The local asset guard does not perform this authenticated remote check.
5. Deploy using the owning Wrangler configuration. Its mandatory build hook
   checks source ancestry, a clean checkout, the production manifest, light-only
   compiled assets and the request accordion. Missing, changed, stale and
   snapshot-mode builds fail closed.
6. Read back the live release manifest and all asset hashes. In a fresh browser,
   check the homepage, example request and an actual closed/refused public
   request under light and dark OS preferences. Verify the actual API-driven
   instruction nouns, four accordion controls and explicit refusal wording.

Keep the rollback target and a receipt naming the source commit, manifest hash,
previous/live Worker versions and observed checks. Never claim a complete
recovery from a successful upload alone.

This guard protects the reviewed checkout's normal release path. It cannot
prevent an older checkout without the hook, a manually changed configuration,
or another credential holder from uploading code directly. Shared release
coordination and restricted deployment credentials remain necessary.
