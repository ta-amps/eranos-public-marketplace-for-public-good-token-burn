"""The workers' Meta client: standard tier only, the key from its file, caps before any call, no fallback.

Every request here goes to an in-process fake transport; nothing reaches the Meta API.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from eranos.model_client import (
    BudgetExhausted,
    ContributorTierRefused,
    Ledger,
    MetaModel,
    ModelUnavailable,
    UsageMeter,
)

SETTINGS: dict[str, Any] = {
    "id": "muse-wonder-1.0",
    "model_display": "Muse Wonder 1.0",
    "base_url": "https://api.meta.ai/v1",
    "max_tokens": 1500,
    "reasoning_effort": "low",
    "prices_usd_per_million": {"input": 4.0, "cached_input": 0.2, "output": 20.0},
}
PLACEHOLDER_CREDENTIAL = "test-meta-key-that-must-never-appear"
USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 500,
    "prompt_tokens_details": {"cached_tokens": 200},
}


def key_file(tmp_path: Path) -> str:
    path = tmp_path / "meta-key"
    path.write_text(PLACEHOLDER_CREDENTIAL + "\n")
    path.chmod(0o600)
    return str(path)


def transport(
    seen: list[httpx.Request],
    *,
    content: str = '{"claims": []}',
    status: int = 200,
    usage: dict[str, Any] | None = USAGE,
    finish: str = "stop",
    error: Exception | None = None,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if error is not None:
            raise error
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "refused"}})
        body: dict[str, Any] = {
            "model": SETTINGS["id"],
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
        }
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle)


def spend(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text()))


def test_a_call_is_the_standard_tier_request_and_records_tokens_and_cost(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    ledger = Ledger(tmp_path / "spend.json", daily_usd=5, total_usd=150)
    model = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=ledger, transport=transport(seen)
    )
    meter = UsageMeter()
    assert model.chat_json("system", "user", meter=meter, temperature=0.2, seed=7) == {"claims": []}
    (request,) = seen
    body = json.loads(request.content)
    assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {PLACEHOLDER_CREDENTIAL}"
    assert body["model"] == "muse-wonder-1.0" and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 1500 and body["reasoning_effort"] == "low" and body["seed"] == 7
    # 1,000 input tokens at $4 (cached ones too: the catalog's cached rate is not used, FB1-017)
    # and 500 output tokens at $20, per million
    expected = round((1000 * 4.0 + 500 * 20.0) / 1e6, 6)
    report = meter.model_report()
    assert report is not None
    assert (report["id"], report["model_display"], report["tier"]) == (
        "muse-wonder-1.0",
        "Muse Wonder 1.0",
        "standard",
    )
    assert report["cost_usd"] == expected and meter.cost_usd == expected
    assert meter.usage()["total_tokens"] == 1500 and report["sampling"] == [
        {"temperature": 0.2, "seed": 7, "reasoning_effort": "low"}
    ]
    saved = spend(tmp_path / "spend.json")
    assert saved["total_usd"] == expected and saved["calls"] == 1  # the reservation was replaced
    assert stat.S_IMODE(os.stat(tmp_path / "spend.json").st_mode) == 0o600
    for text in (
        json.dumps(report),
        json.dumps(model.describe()),
        repr(vars(model)),
        json.dumps(saved),
    ):
        assert PLACEHOLDER_CREDENTIAL not in text


def test_only_the_standard_tier_through_the_meta_api_is_accepted(tmp_path: Path) -> None:
    with pytest.raises(ContributorTierRefused):
        MetaModel({**SETTINGS, "id": "muse-spark-1.3-contributor"})
    for url in (
        "https://api.example.com/v1",
        "http://api.meta.ai/v1",
        "https://api.meta.ai.example.org/v1",
    ):
        with pytest.raises(ValueError, match="Meta API"):
            MetaModel({**SETTINGS, "base_url": url})
    with pytest.raises(ValueError, match="prices"):
        MetaModel({"id": "muse-wonder-1.0"})


def test_a_cap_refuses_the_call_before_anything_is_sent(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    daily = Ledger(tmp_path / "daily.json", daily_usd=5, total_usd=150)
    daily.settle(4.99)
    model = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=daily, transport=transport(seen)
    )
    with pytest.raises(BudgetExhausted, match="daily Meta cap"):
        model.chat_json("system", "user", meter=UsageMeter())
    with pytest.raises(BudgetExhausted):
        model.healthy()
    (tmp_path / "total.json").write_text(json.dumps({"days": {}, "total_usd": 149.99, "calls": 9}))
    total = Ledger(tmp_path / "total.json", daily_usd=5, total_usd=150)
    other = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=total, transport=transport(seen)
    )
    with pytest.raises(BudgetExhausted, match="total Meta cap"):
        other.chat_json("system", "user", meter=UsageMeter())
    assert seen == []  # nothing reached the API
    assert spend(tmp_path / "total.json")["total_usd"] == 149.99  # a refusal reserves nothing


def test_a_failure_is_raised_once_with_no_other_model_tried(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    ledger = Ledger(tmp_path / "spend.json", daily_usd=5, total_usd=150)
    model = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=ledger, transport=transport(seen, status=503)
    )
    meter = UsageMeter()
    with pytest.raises(ModelUnavailable, match="503"):
        model.chat_json("system", "user", meter=meter)
    assert [r.url.host for r in seen] == ["api.meta.ai"] and meter.calls == []
    assert spend(tmp_path / "spend.json")["total_usd"] == 0.0  # a refused call is not counted


def test_a_sent_but_unanswered_call_stays_counted(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    ledger = Ledger(tmp_path / "spend.json", daily_usd=5, total_usd=150)
    lost = httpx.ReadTimeout("no answer")
    model = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=ledger, transport=transport(seen, error=lost)
    )
    with pytest.raises(ModelUnavailable, match="stays counted"):
        model.chat_json("system", "user", meter=UsageMeter())
    assert spend(tmp_path / "spend.json")["total_usd"] == model.estimate(
        len("system") + len("user"), 1500
    )
    refused = httpx.ConnectError("no route")
    never = MetaModel(
        SETTINGS,
        key_file=key_file(tmp_path),
        ledger=Ledger(tmp_path / "b.json", daily_usd=5, total_usd=150),
        transport=transport(seen, error=refused),
    )
    with pytest.raises(ModelUnavailable, match="could not be reached"):
        never.chat_json("system", "user", meter=UsageMeter())
    assert spend(tmp_path / "b.json")["total_usd"] == 0.0  # never sent, never billed


def test_no_key_file_means_no_call(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    model = MetaModel(SETTINGS, key_file=str(tmp_path / "missing"), transport=transport(seen))
    with pytest.raises(ModelUnavailable, match="not readable"):
        model.chat_json("system", "user", meter=UsageMeter())
    with pytest.raises(ModelUnavailable):
        model.healthy()
    assert seen == []


def test_an_answer_cut_off_by_its_token_limit_is_a_recorded_failure(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    model = MetaModel(
        SETTINGS,
        key_file=key_file(tmp_path),
        transport=transport(seen, content="", finish="length"),
    )
    meter = UsageMeter()
    with pytest.raises(ModelUnavailable, match="finish_reason length"):
        model.chat_json("system", "user", meter=meter)
    assert meter.cost_usd > 0 and meter.calls  # its tokens and cost are still in the report


def test_an_answer_without_token_counts_keeps_its_largest_cost(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    ledger = Ledger(tmp_path / "spend.json", daily_usd=5, total_usd=150)
    model = MetaModel(
        SETTINGS, key_file=key_file(tmp_path), ledger=ledger, transport=transport(seen, usage=None)
    )
    meter = UsageMeter()
    model.chat_json("system", "user", meter=meter)
    assert meter.cost_usd == model.estimate(len("system") + len("user"), 1500)
    assert spend(tmp_path / "spend.json")["total_usd"] == meter.cost_usd


@pytest.mark.parametrize(
    "content",
    [
        PLACEHOLDER_CREDENTIAL + "\n",
        f"META_API_KEY={PLACEHOLDER_CREDENTIAL}\n",
        f"# the owner's Meta key\nMETA_API_KEY='{PLACEHOLDER_CREDENTIAL}'\n",
    ],
)
def test_the_key_is_read_from_a_bare_key_file_or_an_env_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "meta.env"
    path.write_text(content)
    path.chmod(0o600)
    seen: list[httpx.Request] = []
    model = MetaModel(SETTINGS, key_file=str(path), transport=transport(seen))
    model.chat_json("system", "user", meter=UsageMeter())
    assert seen[0].headers["authorization"] == f"Bearer {PLACEHOLDER_CREDENTIAL}"


def test_a_file_without_a_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "meta.env"
    path.write_text("TESSERA_URL=https://example.org\nOTHER=1\n")
    with pytest.raises(ModelUnavailable, match="holds no key"):
        MetaModel(SETTINGS, key_file=str(path), transport=transport([])).healthy()


def test_only_the_meta_key_by_its_exact_name_is_read(tmp_path: Path) -> None:
    from eranos.model_client import key_from_text

    assert key_from_text(f"META_API_KEY={PLACEHOLDER_CREDENTIAL}\n") == PLACEHOLDER_CREDENTIAL
    # A worker env file: its Tessera key must never be taken for the Meta key (review M3).
    assert key_from_text("TESSERA_KEY=tsk_example_only\nERANOS_KEY_ID=k_1\n") == ""
    assert key_from_text("OTHER_META_API_KEY=x\n") == ""


@pytest.mark.parametrize(
    "model_id",
    [
        "Muse-Spark-1.3-CONTRIBUTOR",
        "muse-spark-1.3_contributor",
        "muse-spark-1.3.contributor",
        "muse-spark-1.3-contributor ",
    ],
)
def test_a_contributor_id_is_refused_in_any_spelling(model_id: str) -> None:
    with pytest.raises(ContributorTierRefused):
        MetaModel({**SETTINGS, "id": model_id})


def test_the_owners_caps_and_metas_rates_hold_whatever_the_nouns_say(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "spend.json", daily_usd=1_000_000, total_usd=1_000_000)
    assert (ledger.daily_usd, ledger.total_usd) == (
        25.0,
        150.0,
    )  # owner D11; the noun can only lower them
    assert Ledger(tmp_path / "s2.json", daily_usd=1, total_usd=20).daily_usd == 1.0
    cheap = MetaModel({**SETTINGS, "prices_usd_per_million": {"input": 0.01, "output": 0.01}})
    assert (
        cheap.prices["input"] == 4.0 and cheap.prices["output"] == 20.0
    )  # never below the list rate
    for rates in ({"input": 0, "output": 0}, {"input": -1, "output": 20}):
        with pytest.raises(ValueError, match="positive"):
            MetaModel({**SETTINGS, "prices_usd_per_million": rates})
    with pytest.raises(ValueError, match="no rates in code"):
        MetaModel({**SETTINGS, "id": "muse-spark-1.2"})


def test_the_ledger_is_replaced_whole_never_truncated(tmp_path: Path) -> None:
    path = tmp_path / "spend.json"
    ledger = Ledger(path, daily_usd=5, total_usd=150)
    ledger.settle(0.5)
    first = path.stat().st_ino
    ledger.settle(0.25)
    assert path.stat().st_ino != first  # a new file moved into place, not the old one rewritten
    assert spend(path)["total_usd"] == 0.75 and spend(path)["calls"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["spend.json", "spend.json.lock"]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "not a number", None, -3])
def test_a_rate_that_is_not_a_positive_finite_number_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="positive"):
        MetaModel({**SETTINGS, "prices_usd_per_million": {"input": bad, "output": 20.0}})


@pytest.mark.parametrize("bad", [float("nan"), float("-inf"), "x", 0])
def test_a_cap_that_is_not_a_positive_finite_number_refuses_every_call(
    tmp_path: Path, bad: Any
) -> None:
    ledger = Ledger(tmp_path / "spend.json", daily_usd=bad, total_usd=150)
    with pytest.raises(BudgetExhausted):
        ledger.reserve(0.01)


def test_a_cost_or_a_ledger_that_is_not_a_number_never_wipes_the_spend(tmp_path: Path) -> None:
    path = tmp_path / "spend.json"
    ledger = Ledger(path, daily_usd=5, total_usd=150)
    ledger.settle(1.0)
    day = ledger.reserve(0.5)
    ledger.settle(float("nan"), reserved=0.5, day=day)  # keeps the reservation counted
    assert spend(path)["total_usd"] == 1.5
    with pytest.raises(BudgetExhausted, match="not a number"):
        ledger.reserve(float("nan"))
    path.write_text(json.dumps({"days": {}, "total_usd": float("nan"), "calls": 1}))
    with pytest.raises(BudgetExhausted, match="not a number"):
        ledger.reserve(0.01)  # a damaged ledger refuses, it never starts again from zero
