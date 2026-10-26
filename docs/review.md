# Review Guide & Cold-Start Handoff

## Claims to try to break

1. **Try to approve your own draft:** Call `run_review_step` with the same worker name or Tessera key ID used
   in `run_draft_step` (`tests/test_pipeline.py::test_self_review_by_same_worker_or_key_is_refused`).
2. **Try to let an agent run an interview or individual eligibility call:** Create a `WorkflowStep` with
   `kind="interview"` or `"individual_decision"` and `boundary="drafts"`
   (`tests/test_schemas_and_copy.py::test_interviews_and_decisions_must_stay_human_only`).
3. **Try to publish without `SYNTHETIC` marks or with accusatory language:** Omit `SYNTHETIC` from a fixture
   or include banned accusation words (`tests/test_schemas_and_copy.py`).
4. **Try to hardcode a track or kit ID in Python:** Add any track slug or kit ID string constant inside
   `eranos/` (`tests/test_tracks_and_verifier.py::test_neutral_code_names_no_track_or_kit_id`).
