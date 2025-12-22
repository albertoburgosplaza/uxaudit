from __future__ import annotations

from typing import Iterable

from uxaudit.schema import Evidence, Recommendation


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
    evidence = [_normalize_evidence(item) for item in raw.get("evidence", [])]
    evidence = [item for item in evidence if item is not None]
    return Recommendation(
        id=str(raw.get("id") or f"rec-{index:02d}"),
        title=str(raw.get("title") or raw.get("summary") or f"Recommendation {index}"),
        description=str(raw.get("description") or raw.get("details") or ""),
        rationale=raw.get("rationale") or raw.get("reason"),
        priority=_normalize_choice(raw.get("priority"), {"P0", "P1", "P2"}, "P1"),
        impact=_normalize_choice(raw.get("impact"), {"H", "M", "L"}, "M"),
        effort=_normalize_choice(raw.get("effort"), {"S", "M", "L"}, "M"),
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


def _normalize_choice(value: str | None, allowed: set[str], default: str) -> str:
    if not value:
        return default
    normalized = str(value).upper()
    return normalized if normalized in allowed else default


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
