# B4: process requests become generated, tested process packages

When a nonprofit asks for a reusable process, a worker calls `build_process`. Everything is
deterministic and no model is called: each plan piece maps to the vetted operations its own words
name, and the step sentences, how-to and skill text come from fixed templates. Fixed code also packages and tests the result as a Task Object (a seed pack holding a
tested runner, configs for eight agent harnesses and Docker Compose) and a runnable Task (the verb
template). The nonprofit runs it on its own computer or cloud account. Its files never come to us.

- Nouns: the bundle, the kit, the skill, the read-only tool card, the process steps (a procedure that
  needs 0 model tokens per run), the code, the checklist, sources, made-up test cases (no real data), the request,
  and the run-report and person-step templates.
- Verbs: `run-cleaning-process` (an agent, no model), `review-flags` (a person) and `follow-up-missing-details`
  (a person). The build itself is B1's verbs: the split, the pieces, combine, and an eq03 review by a
  different key.
- Surface: the marketplace catalog and its permalink, plus the library. The Teleion Fabric shim and Agora find the package there.
- Infrastructure (existing, nothing new): Teleion Fabric buckets, records, leases and receipts.

## Process classes

- `tabular_cleaning`: cleans spreadsheet exports with the tested runner in `runner/`.
- `handwritten_case_files`: fills a spreadsheet from readings of scans and handwritten notes, with the runner in
  `runner_scans/` and the fixed text in `process_packages/scans.py`. The package never reads an image. The nonprofit's
  own agent or a local OCR tool reads each scan on its own computer and saves one small reading file. The runner checks
  those files against a field list, writes `spreadsheet.csv` and `person-check.csv`, and holds every unclear or
  low-confidence value out of the spreadsheet. A person always checks client text. Tasks: `read-scans` (the nonprofit's
  own agent or tool), `run-reading-process` (an agent, no model), `check-flagged-fields` and
  `follow-up-missing-details` (a person). A request is built only when it names scans or handwriting and asks to type
  them up, read them into a sheet, or read intake or case forms, with no summary, analysis, contact or sending step. Anything else in this class is refused.
  The reviewer also writes its own copy of the whole package from the request and compares every file.

## The handler interface (`b4.build_process.v1`, stable)

```python
import sys; sys.path.insert(0, "<this folder>")
from process_packages import (build_process, draft_piece, review_package, finalize_catalog_record,
                              reuse_signature, reuse_match, ProcessRequestError, SelfReviewRefused)

result = build_process(
    request={"id": "req-...", "description": "...", "output_type": "reusable_process", "frequency": "monthly"},
    plan_part={"pieces": [{"id": "p1", "title": "Profile the columns", "depends_on": [], "claimed_by": "worker-key-id",
                           "output": None}, ...]},
    out_dir=None,             # default ./out
    builder={"id": "...", "key_id": "..."},   # the builder's worker id and key id (the reviewer must differ)
    track_id=None,            # default donor-stewardship-and-privacy for this class (finding F31-B4-04)
    run_docker=True,          # run `docker compose run --rm test` from a new empty folder
)
result["bundle_path"]          # str: out/<pack>.tar.gz, byte-reproducible
result["bundle_sha256"]        # str
result["catalog_record"]       # Teleion Fabric RecordWrite for eranos.catalog/<kit_id>, quarantined until review
result["task_template_record"] # RecordWrite for eranos.verb_templates/<pack>, value.task_spec = the TaskSpec template
result["test_report"]          # dict: passed, failures, checks{...}, pieces, model_calls (always 0)
# documented extras:
result["reuse"]                # the reuse signature (below)
result["solution_record"]      # RecordWrite for eranos.solutions/<pack>: the noun the reuse check finds
result["package_dir"]          # str: the unpacked pack folder
```

- `ProcessRequestError(reason, outcome)` means nothing was built. `outcome` is `refused` (personal data
  in the description), `unknown` (no tested process class fits yet) or `blocked` (bad plan). Record it as the verb's outcome.
- A failing test does not raise. `test_report["passed"]` is False and `failures` names each check.
- Pieces: if a piece's worker already called `draft_piece(request, piece)` and passed the result back as
  `piece["output"]`, that output is used once it passes the same checks. Otherwise the combine step drafts
  the piece. `claimed_by` is copied into the report, so every piece's claimant is on the record.
- Review: `review_package(bundle_path, build_json, {"id", "key_id"})` raises `SelfReviewRefused` when the
  reviewer is the builder (by id or by key). Otherwise it re-checks the SHA-256 and re-runs the container
  test in a clean folder. `finalize_catalog_record(catalog_record, review)` returns the public entry,
  validated as the marketplace's `PublishedKit`.

## In the worker loop

The worker loop loads `eranos_handler.py` (set `ERANOS_PROCESS_HANDLER` to it). That module adapts
the loop's request and plan-part shapes, derives every id, store and key from the request
(`expected_records`), and reviews without trusting build output (review M3). It needs the bundle
fetched by digest, byte-identical vetted files, a minimal environment, no network and resource
limits for the tests, and records that belong to the request. The agreed interface and the
worker-side changes are in [INTERFACE-B1.md](INTERFACE-B1.md).

## The reuse key (`proc2`)

`reuse_signature(description)` is computed with no model, so it costs 0 tokens.

1. Normalize the description: lowercase it, fold accents, and turn every other character into a space.
2. Pick the process class by its words. `tabular_cleaning` needs a sheet word and a cleaning word;
   `handwritten_case_files` needs a handwriting word and a page or file word.
3. Find the class's operations by synonyms (duplicates, double entries and dedupe all mean `dedupe`,
   and so on). Steps every package has (profile, report) are left out.
4. Find the subjects (volunteer sign-ups, donors, members, participants, cases).
5. The key is `proc2-` plus the first 16 hex characters of SHA-256 over the canonical JSON
   `{"class": ..., "operations": [sorted], "subjects": [sorted]}`. The subject is part of the key,
   so a donor-list request with the same steps does not match the volunteer sign-up package.

`reuse_match(request_sig, stored_sig)` returns `exact` (same key), `superset` (same class and
subjects, and the stored package does everything asked plus more) or `none`. The original request and
its rewording both give `proc2-7eefca618400649c`. When a request fits two classes, the first with an operation names the
process, so a request that already had a key keeps it. The planner's keyed reuse needs a reviewed catalog
entry with exactly that one `reuse:` tag, the record key `PRC-7EEFCA-01` and `kind:process_package`.

## Layout

- `process_packages/`: the handler (`handler.py`), the reuse key, the spreadsheet
  class, the seed-pack builder, the packaging and the checks.
- `runner/` and `runner_scans/`: each class's `run_process.py` (standard library only) with its tests and made-up sample files
  (`samples/`, no real data). A package ships its own class's runner. `scripts/make_scan_samples.py` draws the practice scans.
- `vendor/`: copies, with provenance in `vendor/VENDORED.json`. They are the library's `build_packs.py`,
  `validate_packs.py` and `check_public.py` at 1685005; the marketplace's `verify_kit` at 6397473; and
  a persona compiler and a config scanner.
- `out/`: built packages and `<pack>.build.json` (the test report and records).
- `scripts/build.py`, `scripts/review.py`, `scripts/golive.py`.

## Checks

    python3 -m venv .venv && .venv/bin/pip install pydantic   # the checks run kits in this environment
    python3 -m unittest discover -s tests -v          # handler, trust, review, wording and the scan class (no model, no network)
    (cd runner && python3 -m unittest discover -s tests -v)   # the spreadsheet runner's tests
    (cd runner_scans && python3 -m unittest discover -s tests -v)   # the scan runner's tests
    B4_SCAN_DOCKER_TEST=1 python3 -m unittest tests.test_scans   # the scan class with the real container tests
    python3 scripts/build.py requests/first-process.json     # the first process, end to end
