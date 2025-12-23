from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{_short_hex()}"


def _short_hex() -> str:
    return uuid4().hex[:6]


def extract_json(text: str) -> dict[str, object] | list[object]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Empty response")

    if cleaned.startswith("```"):
        cleaned = _strip_fences(cleaned)

    for candidate in _json_candidates(cleaned):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return parsed

    raise ValueError("Unable to parse JSON response")


def _strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    object_match = re.search(r"\{.*\}", text, re.DOTALL)
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))
    if array_match:
        candidates.append(array_match.group(0))
    return candidates


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
