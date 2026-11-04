# The worker loop and the B4 handler: the agreed interface (proposal for the worker builder)

Set `ERANOS_PROCESS_HANDLER=<this folder>/eranos_handler.py`. The handler exposes six functions. Branch
`b4-process-handler` (off `worker-loop` 492c1f3, worktree `functional/builds/eranos-worker-b4`) is a
reference implementation of the worker side. Adopt it or replace it. Its film test is
`test_film_data_cleaning_request_is_built_reviewed_published_and_reused`.

| Function | Who calls it | Contract |
|---|---|---|
| `expected_records(request, plan_part)` | builder and reviewer | Pure function of the planner's brief. Returns `request_id`, `part`, `pack_id`, `kit_id`, `reuse_key`, and `catalog_record`, `task_template_record` and `listed_catalog_record`, each `{store, key}`. Drafts are request-scoped: `eranos.processes/<request>.<part>.<kit_id>` and `eranos.process_templates/<request>.<part>.<pack_id>`. The listed entry is `eranos.catalog/<kit_id>` |
| `build_process(request, plan_part)` | builder | Returns `bundle_path` (inside the handler's own run folder), `bundle_sha256`, `catalog_record` and `task_template_record` at exactly the derived `{store, key}` with `value`, `test_report` (`passed`, `issues`, `tests`) and `ids`. The worker refuses records anywhere else |
| `review_process(package, request, plan_part, *, bundle_path, records, builder_key_id, trusted_builder_keys=None, builder_account_id=None, trusted_account_id=None)` | reviewer | `bundle_path`: the reviewer fetched the blob by `package.blob_sha256` into its own temp folder. `records`: `{name: {value, owner_key_id}}` as read at the derived keys; `builder_key_id`: the build lease's completing key. The build key must be one of `trusted_builder_keys` (required) and both drafts must be owned by it (and by the trusted account when that is given). Returns `passed`, `checks`, `notes`, and `verified`: the derived ids, `value_sha256` for both drafts, and `catalog_value` and `template_value` rebuilt from the bundle and the request, which the worker publishes instead of the drafts. Without `bundle_path` it fails closed |
| `record_digest(value)` | reviewer | The digest to compare with `verified[name]["value_sha256"]` just before publishing |
| `finalize_catalog_value(value, review)` | reviewer | Adds the review fields (keys from the leases, `draft_sha256` = blob digest, `review_receipt` None before the submit) and validates the result as `PublishedKit`. The worker hashes it into `publication_sha256` before the submit, then publishes `{...value, review_receipt, publication_sha256}` to the listed catalog entry. Teleion Fabric's publication guard checks exactly this |
| `reuse_signature(text)` | planner | 0 tokens. A reviewed catalog entry tagged `reuse:<key>` is an exact reuse match (score 1.0) |

The interface is the same for every process class. `handwritten_case_files` needs no worker change: its ids are
`process-scan-reading-<key>` and `PRC-<KEY>-01`, and it publishes on the track `statement-transcription`.

What the review checks, without trusting the build output:

- The bundle's SHA-256 equals the digest it was fetched by.
- Its files are exactly the generator's list for the derived pack and role: a `compose.override.yaml`, `.env` or any other extra file fails the review.
- Every member is a plain file or folder under the derived pack folder (no `..`, links or devices), within size limits.
- The runner, its tests, the sample files, the Dockerfile, compose.yaml, launch.sh and the Makefile are byte-identical to the handler's copies.
- `process.json` validates and does every step the request asks for.
- For `handwritten_case_files`, every file also equals the reviewer's own copy, written from the request and the fixed text.
- The pack's request noun names this request.
- The config supply-chain scan is clean.
- No package config ever reaches Docker. The reviewer runs the vetted tests with plain `docker run`, every flag set by itself: `--pull never --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --cpus 1 --user 65534:65534`, a tmpfs for /tmp, its own checked copy mounted read-only, a time limit inside and outside the container, and `docker rm -f` in `finally`. The builder's own check uses `docker compose -f compose.yaml --env-file /dev/null --project-directory <code>` and runs `compose down` in `finally`.
- Both records were written by the build's key and equal the values rebuilt from the bundle and the request, with exactly one `reuse:` tag and one `request:` tag.

Worker-side changes in the branch, all in `eranos/pipeline/`:

- `process.py`, builder: refuse records outside the derived keys.
- `process.py`, reviewer: derive the ids, fetch the blob, read the records at the derived keys, call `review_process` with `bundle_path` and `records`, and compare the digests. Finalize with `publication_sha256` before the submit. Publish the drafts and list `eranos.catalog/<kit_id>`. The reviewer holds the eq03 grant the catalog needs.
- `reuse.py` and `planner.py`: the keyed exact match (one `reuse:` tag, record key `PRC-<key>-01`, `kind:process_package`).
- `eranos/schemas/records.py`, `verifier.py` and `donor_worker.py`: test cases and practice-review notes use `MADE-UP` wording (the owner's rule); the older mark still validates for the existing example kits. `ERANOS_PROCESS_BUILDER_KEYS` (comma-separated builder key ids) is **required**: a reviewer with a process handler refuses to start without it (`BuilderKeysMissing`), a review without it is sent back, and the handler refuses a build key outside it. B1 sets it to the dedicated builder key id at go-live.

## Builder keys: the exact name and format (agreed for the worker-loop merge)

- Variable: `ERANOS_PROCESS_BUILDER_KEYS`, on the reviewer's unit only.
- Format: one or more Teleion Fabric key ids, comma-separated (`k_a4146f08757b` or `k_a…,k_b…`). Spaces are trimmed and empty entries ignored. At go-live it holds the one dedicated builder key id.
- Required: a reviewer with a process handler refuses to start without it (`BuilderKeysMissing`; branch `b4-process-handler` `9fba6ee`). It is read once at start, never inside the review process.
- Passed to the handler as keyword arguments, because the clean review process (`_clean_review`, `python -I`, `_PASS_ENV` only) does not see the worker's environment:
  - `trusted_builder_keys`: the list above;
  - `builder_key_id`: `build.completed_by_key`;
  - `records`: `{name: {"value": record.value, "owner_key_id": record.owner_key_id}}`.

  In `worker-loop`'s `_RUNNER`:

      kwargs = {"bundle_path": pathlib.Path(bundle), "records": load(records),
                "builder_key_id": load(builder)["key_id"], "trusted_builder_keys": load(builder)["trusted"]}

- `worker-loop` at `bac73a3` still passes values only and no keys. The handler refuses that shape: every process review comes back `needs_revision` until the merge lands. That fails closed, never open.
