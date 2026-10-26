"""Copy and topic guardrails: outputs use neutral operational indicators, never accusations, and never
collect or generate content in prohibited harm categories (AGENTS.md hard rules 4 and 5)."""

from __future__ import annotations

import re

BANNED_ACCUSATIONS = re.compile(
    r"\b(criminal|criminals|trafficker|traffickers|scammer|scammers|fraudster|fraudsters|"
    r"guilty|acting illegally)\b",
    re.IGNORECASE,
)

PROHIBITED_COLLECTION_TOPICS = re.compile(
    r"\b(csam|child sexual|grooming kit|sextortion sample|intimate-image sample|"
    r"revenge porn|self-harm guide|track real person location)\b",
    re.IGNORECASE,
)


def find_accusatory_words(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in BANNED_ACCUSATIONS.finditer(text)})


def check_non_accusatory(text: str) -> str:
    found = find_accusatory_words(text)
    if found:
        raise ValueError(
            f"non-accusatory copy rule violated ({', '.join(found)}); state indicators or checklist items instead"
        )
    return text


def check_safe_topic(text: str) -> str:
    matched = sorted({m.group(0).lower() for m in PROHIBITED_COLLECTION_TOPICS.finditer(text)})
    if matched:
        raise ValueError(
            f"prohibited topic ({', '.join(matched)}): Eranos never collects or generates kits for this category"
        )
    return text
