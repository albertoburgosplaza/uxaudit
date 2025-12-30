from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL_ALIASES = {
    "pro": "gemini-3-pro-preview",
    "flash": "gemini-3-flash-preview",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "UXAUDIT_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"
        ),
    )
    auth_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("UXAUDIT_AUTH_USERNAME"),
    )
    auth_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("UXAUDIT_AUTH_PASSWORD"),
    )


class AuthConfig(BaseModel):
    mode: Literal["none", "form", "storage_state", "basic"] = "none"
    login_url: str | None = None
    post_login_url: str | None = None
    username: str | None = None
    password: str | None = None
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = None
    success_selector: str | None = None
    success_url: str | None = None
    storage_state_path: Path | None = None
    save_storage_state: bool = True


class AuditConfig(BaseModel):
    url: str
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
    headless: bool = True
    style_consistency: bool = True
    style_consistency_batch_size: int = 8
    auth: AuthConfig | None = None

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        return resolve_model(value)


def resolve_model(value: str | None) -> str:
    if not value:
        return MODEL_ALIASES["flash"]
    normalized = value.strip().lower()
    return MODEL_ALIASES.get(normalized, value)
