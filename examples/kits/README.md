# Synthetic Example Kit Bundles

Each file `examples/kits/*.json` holds a synthetic request, volunteer agent draft, optional steward
sign-off payload, and independent review decision exercised end-to-end by `make verify-examples`
(`eq01 -> eq02 -> eq03 -> eranos.catalog`).

Every fixture input begins with `SYNTHETIC:` -- no real client, worker, caller, or donor data is ever
stored in this repository.
