from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def write_json(path: Path, payload: BaseModel | dict | list) -> None:
    data: Any
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n")
