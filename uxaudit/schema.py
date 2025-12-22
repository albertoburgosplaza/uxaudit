from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    screenshot_id: str
    note: str | None = None
    location: str | None = None


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    description: str
    rationale: str | None = None
    priority: Literal["P0", "P1", "P2"] = "P1"
    impact: Literal["H", "M", "L"] = "M"
    effort: Literal["S", "M", "L"] = "M"
    evidence: list[Evidence] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PageTarget(BaseModel):
    id: str
    url: str
    title: str | None = None


class SectionTarget(BaseModel):
    id: str
    page_id: str
    title: str | None = None
    selector: str | None = None


class ScreenshotArtifact(BaseModel):
    id: str
    page_id: str
    section_id: str | None = None
    path: str
    kind: Literal["full_page", "section"] = "full_page"
    width: int
    height: int


class Manifest(BaseModel):
    run_id: str
    url: str
    model: str
    started_at: datetime
    pages: list[PageTarget]
    sections: list[SectionTarget]
    screenshots: list[ScreenshotArtifact]


class AuditResult(BaseModel):
    run_id: str
    url: str
    model: str
    started_at: datetime
    completed_at: datetime
    pages: list[PageTarget]
    sections: list[SectionTarget]
    screenshots: list[ScreenshotArtifact]
    recommendations: list[Recommendation]
    analysis: dict | None = None
    raw_response: list[str] | str | None = None
