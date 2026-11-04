# Recorded example runs

Each `examples/runs/<kit id>.json` is an evidence noun written by `make record-runs`
(`eranos record-example-runs`). It records one run of the repository's own pipeline over one example
kit, on a throwaway local Teleion Fabric store: the record of each verb (check on `eq01`, build on `eq02`,
independent review on `eq03`) with its worker and key labels, the draft digest and verification
summary, any steward parking, the publication digest, the digests of the example file and of the
composed inputs, both repositories' commits and whether their trees were clean, the kind of computer
it ran on (read from the DMI chassis type only) and the number of model calls, which is zero.

These are example runs on one computer with made-up data. They are not hosted volunteer runs,
evaluations or evidence that a kit helps a real organization. `tests/test_example_runs.py` fails when
an example or its seed pack changes after its run, so the runs are recorded again.
