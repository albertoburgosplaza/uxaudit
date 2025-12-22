from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL_ALIASES = {
    "pro": "gemini-3-pro-preview",
    "flash": "gemini-3-flash-preview",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("UXAUDIT_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )


class AuditConfig(BaseModel):
    url: HttpUrl
    model: str = Field(default=MODEL_ALIASES["flash"])
    max_pages: int = 1
    max_total_screenshots: int = 1
    max_sections_per_page: int = 8
    output_dir: Path = Path("runs")
    viewport_width: int = 1440
    viewport_height: int = 900
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "networkidle"
    timeout_ms: int = 45_000
    user_agent: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: str | None) -> str:
        return resolve_model(value)


def resolve_model(value: str | None) -> str:
    if not value:
        return MODEL_ALIASES["flash"]
    normalized = value.strip()
    alias_key = normalized.lower()
    if alias_key in MODEL_ALIASES:
        return MODEL_ALIASES[alias_key]
    if normalized in MODEL_ALIASES.values():
        return normalized

    warnings.warn(
        f"Unknown model alias '{value}'. Using '{normalized}' as provided.",
        stacklevel=2,
    )
    return normalized
