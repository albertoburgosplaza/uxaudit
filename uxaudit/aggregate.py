from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypeVar, cast

from uxaudit.schema import Evidence, Recommendation

Priority = Literal["P0", "P1", "P2"]
Impact = Literal["H", "M", "L"]
Effort = Literal["S", "M", "L"]

PRIORITIES: set[Priority] = {"P0", "P1", "P2"}
IMPACTS: set[Impact] = {"H", "M", "L"}
EFFORTS: set[Effort] = {"S", "M", "L"}

TChoice = TypeVar("TChoice", bound=str)


def normalize_recommendations(raw: dict | list | None) -> list[Recommendation]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = raw.get("recommendations", []) if isinstance(raw, dict) else []

    normalized: list[Recommendation] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        normalized.append(_from_raw(item, index))
    return normalized


def _from_raw(raw: dict, index: int) -> Recommendation:
    evidence_items = [_normalize_evidence(item) for item in raw.get("evidence", [])]
    evidence: list[Evidence] = [item for item in evidence_items if item is not None]
    return Recommendation(
        id=str(raw.get("id") or f"rec-{index:02d}"),
        title=str(raw.get("title") or raw.get("summary") or f"Recommendation {index}"),
        description=str(raw.get("description") or raw.get("details") or ""),
        rationale=raw.get("rationale") or raw.get("reason"),
        priority=_normalize_choice(raw.get("priority"), PRIORITIES, "P1"),
        impact=_normalize_choice(raw.get("impact"), IMPACTS, "M"),
        effort=_normalize_choice(raw.get("effort"), EFFORTS, "M"),
        evidence=evidence,
        tags=_normalize_tags(raw.get("tags")),
    )


def _normalize_evidence(raw: dict | None) -> Evidence | None:
    if not isinstance(raw, dict):
        return None
    screenshot_id = raw.get("screenshot_id")
    if not screenshot_id:
        return None
    return Evidence(
        screenshot_id=str(screenshot_id),
        note=_string_or_none(raw.get("note")),
        location=_string_or_none(raw.get("location")),
    )


def _normalize_tags(value: Iterable[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _normalize_choice(
    value: str | None, allowed: set[TChoice], default: TChoice
) -> TChoice:
    if not value:
        return default
    normalized = str(value).upper()
    if normalized in allowed:
        return cast(TChoice, normalized)
    return default


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
