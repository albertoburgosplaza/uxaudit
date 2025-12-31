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


class RedesignBrief(BaseModel):
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)
    must_keep: list[str] = Field(default_factory=list)


class RedesignConcept(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    page_id: str
    screenshot_id: str
    title: str
    narrative: str | None = None
    experience_goals: list[str] = Field(default_factory=list)
    layout_changes: list[str] = Field(default_factory=list)
    visual_style: str | None = None
    palette: list[str] = Field(default_factory=list)
    typography: list[str] = Field(default_factory=list)
    component_changes: list[str] = Field(default_factory=list)
    image_prompt: str
    render_notes: str | None = None
    render_aspect_ratio: str | None = None
    render_image_size: str | None = None
    render_frame: str | None = None
    image_path: str | None = None
    rendered: bool = False


class PageTarget(BaseModel):
    id: str
    url: str
    title: str | None = None
    auth_state: AuthState | None = None


class SectionTarget(BaseModel):
    id: str
    page_id: str
    title: str | None = None
    selector: str | None = None
    auth_state: AuthState | None = None


class ScreenshotArtifact(BaseModel):
    id: str
    page_id: str
    section_id: str | None = None
    path: str
    kind: Literal["full_page", "section"] = "full_page"
    width: int
    height: int
    auth_state: AuthState | None = None


class Manifest(BaseModel):
    run_id: str
    url: str
    model: str
    started_at: datetime
    pages: list[PageTarget]
    sections: list[SectionTarget]
    screenshots: list[ScreenshotArtifact]
    auth: AuthSummary | None = None


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
    auth: AuthSummary | None = None


class RedesignResult(BaseModel):
    run_id: str
    url: str
    model: str
    started_at: datetime
    completed_at: datetime
    pages: list[PageTarget]
    screenshots: list[ScreenshotArtifact]
    concepts: list[RedesignConcept]
    brief: RedesignBrief | None = None
    render_model: str | None = None
    render_instructions: list[str] = Field(default_factory=list)
    analysis: dict | None = None
    raw_response: list[str] | str | None = None
    auth: AuthSummary | None = None


AuthState = Literal["pre_login", "authenticated"]


class AuthSummary(BaseModel):
    mode: str
    login_url: str | None = None
    post_login_url: str | None = None
    success_selector: str | None = None
    success_url: str | None = None
    storage_state_path: str | None = None
