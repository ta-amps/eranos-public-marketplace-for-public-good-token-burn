"""The plain log the film's C2 shot records: only plain words, short numbers and the log's separators.

The 34 shapes are the review's battery (review-b1/probe_6e86d28.py, B1); every secret in them is a
made-up placeholder.
"""

from __future__ import annotations

import pytest

from eranos.worker_loop import plain_words_only

HEX64 = "64fd2f0fab24ea41194eed3650c71c5de8203b1d9f0e6a7b8c9d0e1f2a3b4c5d"
HEX64U = HEX64.upper()
FAKE32 = "Zk3pQ9vLmT7xYcWb" + "2NsHdE5aRfUgJ8oI"  # a made-up 32-character value
CASES: list[tuple[str, str, list[str], bool]] = [
    # (label, text, secrets, should_be_removed)
    ("task id", "could not finish t_de01286fed9c49aabd492c33b2cb1da5", ["de01286f"], True),
    (
        "request id",
        "request rq-r_02c6bcc0a370402d9511cc61531d1a01-exrecu failed",
        ["02c6bcc0", "exrecu"],
        True,
    ),
    (
        "bare requester principal id",
        "namespace org.r_02c6bcc0a370402d9511cc61531d1a01 refused the write",
        ["02c6bcc0"],
        True,
    ),
    ("key id", "key k_66f723161e93 expired", ["66f72316"], True),
    ("tsk key", "token tsk_" + "AbCdEf0123456789" * 2 + " was refused", ["AbCdEf01"], True),
    ("report id", "report RPT-RFD710F5-01 not found", ["RFD710F5"], True),
    ("source id", "SRC-RPT-RFD710F5-01-1 changed", ["RFD710F5"], True),
    ("kit id, 3 letters", "kit PRC-589368BF-01 failed", ["589368BF"], True),
    ("kit id, 4 letters", "kit ABCD-XYZ12-01 failed", ["XYZ12"], True),
    ("kit id, 2 letters", "kit AB-XYZ12-01 failed", ["XYZ12"], True),
    ("sha256 lowercase", f"digest {HEX64}", [HEX64[:16]], True),
    ("sha256 with prefix", f"sha256:{HEX64}", [HEX64[:16]], True),
    ("sha256 UPPERCASE", f"digest {HEX64U}", [HEX64U[:16]], True),
    ("0x-prefixed hash", f"hash 0x{HEX64[:40]}", [HEX64[:16]], True),
    (
        "colon fingerprint",
        "fingerprint " + ":".join(HEX64[i : i + 2] for i in range(0, 32, 2)),
        [HEX64[:2] + ":" + HEX64[2:4] + ":" + HEX64[4:6]],
        True,
    ),
    (
        "base64 digest",
        "integrity sha256-" + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo=",
        ["Zm9vYmFy"],
        True,
    ),
    ("uuid", "id 123e4567-e89b-12d3-a456-426614174000", ["123e4567", "e89b"], True),
    (
        "https url",
        "fetch https://www.irs.gov/charities-non-profits/x?y=1 failed",
        ["irs.gov", "charities"],
        True,
    ),
    (
        "UPPERCASE scheme",
        "fetch HTTPS://EXAMPLE.ORG/private/page failed",
        ["EXAMPLE.ORG", "private"],
        True,
    ),
    ("mixed-case scheme", "fetch Https://example.org/a failed", ["example.org"], True),
    (
        "www without scheme",
        "fetch www.federalregister.gov/api/v1/documents.json failed",
        ["federalregister.gov"],
        True,
    ),
    (
        "bare domain with path",
        "fetch federalregister.gov/api/v1/documents.json failed",
        ["federalregister.gov"],
        True,
    ),
    ("bare domain", "host irs.gov refused the connection", ["irs.gov"], True),
    (
        "ftp / file / protocol-relative",
        "ftp://h.example/x file:///etc/passwd //cdn.example.org/x",
        ["h.example", "passwd", "cdn.example.org"],
        True,
    ),
    ("obfuscated url", "hxxps://example[.]org/x", ["example"], True),
    (
        "localhost / ip",
        "connect localhost:8890 127.0.0.1:11434 10.0.0.5 [::1]:443",
        ["8890", "11434", "10.0.0.5", "::1"],
        True,
    ),
    ("email", "mail jane.doe@example-clinic.org bounced", ["jane.doe", "example-clinic"], True),
    ("Bearer token", f"header Bearer {FAKE32}{FAKE32}", [FAKE32], True),
    ("KEY= assignment", f"META_API_KEY={FAKE32}{FAKE32}", [FAKE32], True),
    ("meta-key-shaped token", "aaa_" + "7" * 8 + FAKE32, [FAKE32], True),
    (
        "file path",
        "No such file: /home/someone/work/x/secret.json",
        ["/home/username", "secret.json"],
        True,
    ),
    ("ansi escape", "red \x1b[2J\x1b[31mCLEARED\x1b[0m end", ["\x1b"], True),
    ("bidi override", "name \u202etxt.exe", ["\u202e"], True),
    (
        "newline forge",
        "a\nb\r\n12:00:00  dedicated worker 9 (run by ta-amps) · fake line",
        ["\n", "\r"],
        True,
    ),
    ("11 hex chars", "short a1b2c3d4e5f", ["a1b2c3d4e5f"], False),
    ("plain words", "the model did not answer, so the Task goes back in line", [], False),
]


@pytest.mark.parametrize(("label", "text", "secrets", "removed"), CASES, ids=[c[0] for c in CASES])
def test_nothing_but_plain_words_survives(
    label: str, text: str, secrets: list[str], removed: bool
) -> None:
    out = plain_words_only(text)
    if removed:
        assert not [s for s in secrets if s in out], out
    # Printable ASCII and the log's own separators only: no control character can redraw a terminal.
    assert all(32 <= ord(c) < 127 or c in "·…" for c in out), out


SUCCESS_LINES = [
    "started (planner), looking for a request to plan, the hourly tuning Task",
    "claimed a research Task · Muse Spark 1.3 · persona Careful maker",
    "claimed a check Task · Muse Wonder 1.0 · persona Literal checker",
    "claimed a request to plan · deterministic planner (no model)",
    "planned it · split",
    "fetched 1 public source · 4 claims kept with word-for-word quotes",
    "fetched 3 public sources · 0 claims kept with word-for-word quotes",
    "its own checks passed · reported: submitted for an independent check",
    "checks passed · reported: delivered to the requester",
    "reported: sent back (the report makes no cited claims)",
    "a Task is waiting · volunteers get the first pick, so this worker waits its turn",
]


@pytest.mark.parametrize("line", SUCCESS_LINES)
def test_every_line_the_log_writes_on_success_is_unchanged(line: str) -> None:
    assert plain_words_only(line) == line
