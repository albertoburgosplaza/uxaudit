from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from google.genai import types

from uxaudit.auth import AuthResult, perform_login
from uxaudit.browser import BrowserConfig, browser_context
from uxaudit.capture import capture_full_page
from uxaudit.config import AuditConfig, AuthConfig, Settings
from uxaudit.crawler import filter_links, normalize_url
from uxaudit.gemini_client import GeminiClient
from uxaudit.prompts import build_redesign_prompt
from uxaudit.report import write_json
from uxaudit.schema import (
    AuthState,
    AuthSummary,
    Manifest,
    PageTarget,
    RedesignBrief,
    RedesignConcept,
    RedesignResult,
    ScreenshotArtifact,
)
from uxaudit.utils import build_run_id, ensure_dir

logger = logging.getLogger(__name__)

MANUAL_RENDER_INSTRUCTIONS = [
    "Use the base screenshot as the reference image for NanoBanana Pro.",
    "Paste the concept image_prompt and keep the framing consistent.",
    "Export each render as a PNG to the target image_path.",
]

AUTO_RENDER_INSTRUCTIONS = [
    "Auto-rendered using the NanoBanana Pro image model and the base screenshot.",
    "Re-run with --render-mode none to skip auto generation.",
    "You can replace any PNG in image_path with manual renders.",
]

RENDER_MODEL_ALIASES = {
    "nano-banana-pro": "gemini-3-pro-image-preview",
    "nanobanana-pro": "gemini-3-pro-image-preview",
    "nano-banana": "gemini-2.5-flash-image",
    "nanobanana": "gemini-2.5-flash-image",
}
DEFAULT_RENDER_MODEL = "nano-banana-pro"

ALLOWED_ASPECT_RATIOS = {
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
}
VERTICAL_ASPECT_RATIOS = {"2:3", "3:4", "4:5", "9:16"}
HORIZONTAL_ASPECT_RATIOS = {"3:2", "4:3", "5:4", "16:9", "21:9"}
ALLOWED_IMAGE_SIZES = {"1K", "2K", "4K"}


def run_redesign(
    config: AuditConfig,
    settings: Settings,
    brief: RedesignBrief | None,
    variants: int,
    render_mode: Literal["auto", "none"] = "auto",
    render_overwrite: bool = False,
    render_model: str = DEFAULT_RENDER_MODEL,
) -> tuple[RedesignResult, Path]:
    _validate_redesign_limits(config, variants)

    run_id = build_run_id()
    run_dir = config.output_dir / run_id
    screenshots_dir = run_dir / "screenshots"
    redesign_dir = run_dir / "redesign"
    ensure_dir(screenshots_dir)
    ensure_dir(redesign_dir)

    started_at = datetime.now(timezone.utc)
    client = GeminiClient(api_key=settings.api_key or "", model=config.model)

    pages: list[PageTarget] = []
    screenshots: list[ScreenshotArtifact] = []
    concepts: list[RedesignConcept] = []
    analysis_items: list[dict] = []
    raw_responses: list[str] = []

    page_counter = 0
    remaining_screenshots = config.max_total_screenshots

    auth = _resolve_auth(config, settings)
    auth_summary = None

    browser_config = BrowserConfig(
        viewport_width=config.viewport_width,
        viewport_height=config.viewport_height,
        user_agent=config.user_agent,
        headless=config.headless,
    )

    def analyze_and_collect(
        page: PageTarget,
        screenshot: ScreenshotArtifact,
        image_path: Path,
        auth_state: AuthState | None,
        page_index: int,
    ) -> None:
        brief_block = _build_brief_block(brief)
        prompt = build_redesign_prompt(page, variants, brief_block, auth_state)
        analysis, raw_response = client.analyze_image(prompt, image_path)
        normalized, summary = _normalize_concepts(
            analysis, variants, page, screenshot, page_index
        )
        concepts.extend(normalized)
        analysis_items.append(
            {
                "page_id": page.id,
                "screenshot_id": screenshot.id,
                "url": page.url,
                "title": page.title,
                "auth_state": auth_state,
                "summary": summary,
                "analysis": analysis if isinstance(analysis, dict) else None,
            }
        )
        if raw_response:
            raw_responses.append(raw_response)

    def capture_page(
        context,
        url: str,
        auth_state: AuthState,
    ) -> tuple[str, list[str]] | None:
        nonlocal page_counter, remaining_screenshots
        if remaining_screenshots <= 0:
            return None

        page_counter += 1
        screenshot_path = screenshots_dir / f"page-{page_counter}.png"

        try:
            capture = capture_full_page(
                url,
                screenshot_path,
                config,
                max_sections=0,
                context=context,
            )
        except Exception as exc:
            logger.warning("Failed to capture %s: %s", url, exc)
            return None

        page = PageTarget(
            id=f"page-{page_counter}",
            url=capture.url,
            title=capture.title,
            auth_state=auth_state,
        )
        screenshot = ScreenshotArtifact(
            id=f"shot-{page_counter}",
            page_id=page.id,
            path=str(screenshot_path.relative_to(run_dir)),
            width=config.viewport_width,
            height=config.viewport_height,
            auth_state=auth_state,
        )
        pages.append(page)
        screenshots.append(screenshot)
        remaining_screenshots -= 1

        analyze_and_collect(page, screenshot, screenshot_path, auth_state, page_counter)

        return capture.url, capture.links

    auth_result = AuthResult(storage_state_path=None, landing_url=None)
    auth_state: AuthState = "authenticated"
    start_url = config.url

    with browser_context(
        browser_config,
        storage_state=_storage_state_path(auth),
        http_credentials=_http_credentials(auth),
    ) as context:
        if auth and auth.mode == "form":
            auth_result = perform_login(context, auth, config, run_dir)
        if auth and auth.post_login_url:
            start_url = auth.post_login_url

        queue = deque([start_url])
        seen: set[str] = set()
        pages_in_crawl = 0

        while queue and pages_in_crawl < config.max_pages:
            if remaining_screenshots <= 0:
                break
            url = queue.popleft()
            normalized = normalize_url(url)
            if normalized in seen:
                continue
            seen.add(normalized)

            result = capture_page(context, url, auth_state)
            if result is None:
                continue
            pages_in_crawl += 1

            _, links = result
            for link in filter_links(links, config.url):
                if link not in seen:
                    queue.append(link)

    if not pages:
        raise RuntimeError("No pages were captured. Check the URL and try again.")

    if auth:
        auth_summary = AuthSummary(
            mode=auth.mode,
            login_url=auth.login_url,
            post_login_url=auth.post_login_url,
            success_selector=auth.success_selector,
            success_url=auth.success_url,
            storage_state_path=_auth_storage_state_for_report(
                auth, auth_result, run_dir
            ),
        )

    manifest = Manifest(
        run_id=run_id,
        url=config.url,
        model=config.model,
        started_at=started_at,
        pages=pages,
        sections=[],
        screenshots=screenshots,
        auth=auth_summary,
    )
    write_json(run_dir / "manifest.json", manifest)

    render_items: list[dict] = []
    render_instructions = MANUAL_RENDER_INSTRUCTIONS
    resolved_render_model = resolve_render_model(render_model)
    if render_mode != "none":
        render_items = _render_concepts(
            client,
            run_dir,
            concepts,
            screenshots,
            render_overwrite,
            resolved_render_model,
        )
        render_instructions = AUTO_RENDER_INSTRUCTIONS

    analysis_payload: dict | None = None
    if analysis_items or render_items:
        analysis_payload = {"items": analysis_items}
        if render_items:
            analysis_payload["render_items"] = render_items

    completed_at = datetime.now(timezone.utc)
    result = RedesignResult(
        run_id=run_id,
        url=config.url,
        model=config.model,
        started_at=started_at,
        completed_at=completed_at,
        pages=pages,
        screenshots=screenshots,
        concepts=concepts,
        brief=brief,
        render_model=resolved_render_model if render_mode != "none" else None,
        render_instructions=render_instructions,
        analysis=analysis_payload,
        raw_response=raw_responses or None,
        auth=auth_summary,
    )
    write_json(run_dir / "redesign.json", result)
    _write_redesign_preview(run_dir, result)

    return result, run_dir


def _build_brief_block(brief: RedesignBrief | None) -> str:
    if not brief:
        return ""
    lines = []
    if brief.goals:
        lines.append(f"- Goals: {', '.join(brief.goals)}")
    if brief.constraints:
        lines.append(f"- Constraints: {', '.join(brief.constraints)}")
    if brief.style_notes:
        lines.append(f"- Style notes: {', '.join(brief.style_notes)}")
    if brief.must_keep:
        lines.append(f"- Must keep: {', '.join(brief.must_keep)}")
    if not lines:
        return ""
    return "Brief:\n" + "\n".join(lines)


def _normalize_concepts(
    raw: dict | list | None,
    variants: int,
    page: PageTarget,
    screenshot: ScreenshotArtifact,
    page_index: int,
) -> tuple[list[RedesignConcept], str | None]:
    if raw is None:
        return _fallback_concepts(variants, page, screenshot, page_index), None
    if isinstance(raw, list):
        concepts_raw = raw
        summary = None
    else:
        concepts_raw = raw.get("concepts", []) if isinstance(raw, dict) else []
        summary = _string_or_none(raw.get("summary")) if isinstance(raw, dict) else None

    concepts: list[RedesignConcept] = []
    for index in range(variants):
        item = concepts_raw[index] if index < len(concepts_raw) else {}
        if not isinstance(item, dict):
            item = {}
        concept_id = f"concept-{page_index:02d}-{index + 1:02d}"
        title = _string_or_none(item.get("title")) or f"Concept {index + 1}"
        narrative = _string_or_none(item.get("narrative") or item.get("story"))
        experience_goals = _string_list(
            item.get("experience_goals") or item.get("goals")
        )
        layout_changes = _string_list(
            item.get("layout_changes") or item.get("structure_changes")
        )
        visual_style = _string_or_none(item.get("visual_style") or item.get("style"))
        palette = _string_list(item.get("palette") or item.get("colors"))
        typography = _string_list(item.get("typography") or item.get("fonts"))
        component_changes = _string_list(
            item.get("component_changes") or item.get("components")
        )
        render_aspect_ratio = _string_or_none(
            item.get("render_aspect_ratio")
            or item.get("render_aspect")
            or item.get("aspect_ratio")
        )
        render_image_size = _string_or_none(
            item.get("render_image_size")
            or item.get("image_size")
            or item.get("resolution")
        )
        render_frame = _string_or_none(item.get("render_frame") or item.get("frame"))
        image_prompt = _string_or_none(
            item.get("image_prompt")
            or item.get("nanobanana_prompt")
            or item.get("prompt")
        )
        render_notes = _string_or_none(item.get("render_notes") or item.get("notes"))

        if not image_prompt:
            image_prompt = _fallback_image_prompt(title, visual_style, palette)

        concepts.append(
            RedesignConcept(
                id=concept_id,
                page_id=page.id,
                screenshot_id=screenshot.id,
                title=title,
                narrative=narrative,
                experience_goals=experience_goals,
                layout_changes=layout_changes,
                visual_style=visual_style,
                palette=palette,
                typography=typography,
                component_changes=component_changes,
                image_prompt=image_prompt,
                render_notes=render_notes,
                render_aspect_ratio=render_aspect_ratio,
                render_image_size=render_image_size,
                render_frame=render_frame,
                image_path=str(Path("redesign") / f"{concept_id}.png"),
            )
        )

    return concepts, summary


def _fallback_concepts(
    variants: int,
    page: PageTarget,
    screenshot: ScreenshotArtifact,
    page_index: int,
) -> list[RedesignConcept]:
    concepts: list[RedesignConcept] = []
    for index in range(variants):
        concept_id = f"concept-{page_index:02d}-{index + 1:02d}"
        title = f"Concept {index + 1}"
        concepts.append(
            RedesignConcept(
                id=concept_id,
                page_id=page.id,
                screenshot_id=screenshot.id,
                title=title,
                image_prompt=_fallback_image_prompt(title, None, []),
                image_path=str(Path("redesign") / f"{concept_id}.png"),
            )
        )
    return concepts


def _fallback_image_prompt(
    title: str,
    visual_style: str | None,
    palette: list[str],
) -> str:
    style_block = f" Style: {visual_style}." if visual_style else ""
    palette_block = f" Palette: {', '.join(palette)}." if palette else ""
    return (
        "Redesign the UI screenshot with a bold new layout."
        f" Concept: {title}.{style_block}{palette_block}"
        " Preserve content meaning but re-architect the hierarchy."
    )


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return [item for item in items if item]
    return [str(value)]


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_render_model(value: str | None) -> str:
    if not value:
        return RENDER_MODEL_ALIASES[DEFAULT_RENDER_MODEL]
    normalized = value.strip().lower().replace(" ", "-")
    return RENDER_MODEL_ALIASES.get(normalized, value)


def _render_concepts(
    client: GeminiClient,
    run_dir: Path,
    concepts: list[RedesignConcept],
    screenshots: list[ScreenshotArtifact],
    render_overwrite: bool,
    render_model: str,
) -> list[dict]:
    shot_by_id = {shot.id: run_dir / shot.path for shot in screenshots}
    items: list[dict] = []
    for concept in concepts:
        image_path = _resolve_concept_image_path(run_dir, concept)
        aspect_ratio = _resolve_concept_aspect_ratio(concept)
        render_frame = _resolve_render_frame(concept, aspect_ratio)
        image_size = _resolve_image_size(concept, render_model)
        if aspect_ratio and not concept.render_aspect_ratio:
            concept.render_aspect_ratio = aspect_ratio
        if render_frame and not concept.render_frame:
            concept.render_frame = render_frame
        if image_size and not concept.render_image_size:
            concept.render_image_size = image_size
        image_config = _build_image_config(
            render_model,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )

        if image_path.exists() and not render_overwrite:
            concept.rendered = True
            items.append(
                {
                    "concept_id": concept.id,
                    "status": "skipped_existing",
                    "image_path": str(image_path.relative_to(run_dir)),
                    "aspect_ratio": aspect_ratio,
                    "image_size": image_size,
                }
            )
            continue

        prompt = _build_render_prompt(concept, aspect_ratio, render_frame)
        reference_path = shot_by_id.get(concept.screenshot_id)
        image_bytes = None
        method = None
        error = None

        if reference_path and reference_path.exists():
            try:
                image_bytes = client.edit_image(
                    prompt,
                    reference_path,
                    model=render_model,
                    image_config=image_config,
                )
                if image_bytes:
                    method = "edit"
            except Exception as exc:
                error = f"edit_image_failed: {exc}"
                logger.warning("Edit render failed for %s: %s", concept.id, exc)

        if image_bytes is None:
            try:
                image_bytes = client.generate_image(
                    prompt,
                    model=render_model,
                    image_config=image_config,
                )
                if image_bytes:
                    method = "generate"
            except Exception as exc:
                error = f"generate_image_failed: {exc}"
                logger.warning("Generate render failed for %s: %s", concept.id, exc)

        if image_bytes:
            ensure_dir(image_path.parent)
            image_path.write_bytes(image_bytes)
            concept.rendered = True
            status = "generated"
        else:
            concept.rendered = False
            status = "failed"

        item = {
            "concept_id": concept.id,
            "status": status,
            "method": method,
            "image_path": str(image_path.relative_to(run_dir)),
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }
        if error:
            item["error"] = _truncate_error(error)
        items.append(item)

    return items


def _resolve_concept_image_path(run_dir: Path, concept: RedesignConcept) -> Path:
    if concept.image_path:
        return run_dir / concept.image_path
    image_path = run_dir / "redesign" / f"{concept.id}.png"
    concept.image_path = str(image_path.relative_to(run_dir))
    return image_path


def _build_render_prompt(
    concept: RedesignConcept,
    aspect_ratio: str | None,
    render_frame: str | None,
) -> str:
    parts = [
        "Redesign the provided UI screenshot with a bold new visual direction.",
        "Keep the same content meaning and hierarchy.",
        "Show the full page in one frame (hero through footer).",
        f"Concept: {concept.title}.",
    ]
    if concept.narrative:
        parts.append(concept.narrative)
    if concept.visual_style:
        parts.append(f"Visual style: {concept.visual_style}.")
    if concept.palette:
        parts.append(f"Palette: {', '.join(concept.palette)}.")
    if concept.typography:
        parts.append(f"Typography: {', '.join(concept.typography)}.")
    if concept.layout_changes:
        parts.append(f"Layout changes: {'; '.join(concept.layout_changes)}.")
    if concept.component_changes:
        parts.append(f"Component changes: {'; '.join(concept.component_changes)}.")
    if concept.image_prompt:
        parts.append(concept.image_prompt)
    frame_hint = _render_frame_hint(render_frame, aspect_ratio, concept.render_notes)
    if frame_hint:
        parts.append(frame_hint)
    if aspect_ratio:
        parts.append(f"Aspect ratio: {aspect_ratio}.")
    if concept.render_notes:
        parts.append(f"Render notes: {concept.render_notes}.")
    return " ".join(parts)


def _resolve_concept_aspect_ratio(concept: RedesignConcept) -> str | None:
    ratio = _normalize_aspect_ratio(concept.render_aspect_ratio)
    if ratio:
        return ratio
    ratio = _extract_aspect_ratio(concept.render_notes or "")
    if ratio:
        return ratio
    text = " ".join(concept.layout_changes or [])
    if concept.render_frame:
        text = f"{concept.render_frame} {text}"
    text = f"{text} {concept.render_notes or ''}".lower()
    if _contains_any(text, ["vertical", "scroll", "single-column", "single column"]):
        return "9:16"
    if _contains_any(text, ["square", "grid detail", "detail view"]):
        return "1:1"
    if _contains_any(text, ["wide", "horizontal"]):
        return "16:9"
    return "9:16"


def _resolve_render_frame(
    concept: RedesignConcept, aspect_ratio: str | None
) -> str | None:
    if concept.render_frame:
        return concept.render_frame
    text = " ".join(concept.layout_changes or [])
    text = f"{text} {concept.render_notes or ''}".lower()
    if aspect_ratio in VERTICAL_ASPECT_RATIOS or _contains_any(
        text, ["vertical", "scroll", "single-column", "single column"]
    ):
        return "full_page_vertical"
    if _contains_any(text, ["wide", "horizontal"]):
        return "full_page_horizontal"
    return "full_page_vertical"


def _resolve_image_size(concept: RedesignConcept, render_model: str) -> str | None:
    size = _normalize_image_size(concept.render_image_size)
    if size:
        return size
    if _supports_image_config(render_model):
        return "2K"
    return None


def _build_image_config(
    render_model: str,
    aspect_ratio: str | None,
    image_size: str | None,
) -> types.ImageConfig | None:
    if not _supports_image_config(render_model):
        return None
    if not aspect_ratio and not image_size:
        return None
    return types.ImageConfig(
        aspect_ratio=aspect_ratio,
        image_size=image_size,
    )


def _supports_image_config(render_model: str) -> bool:
    return render_model.startswith("gemini-3-pro-image")


def _render_frame_hint(
    render_frame: str | None,
    aspect_ratio: str | None,
    render_notes: str | None,
) -> str | None:
    frame = (render_frame or "").lower()
    if "vertical" in frame or aspect_ratio in VERTICAL_ASPECT_RATIOS:
        return (
            "Framing: full-page vertical capture from hero to footer "
            "in a single tall frame."
        )
    if "horizontal" in frame or aspect_ratio in HORIZONTAL_ASPECT_RATIOS:
        return (
            "Framing: full-page wide capture in one frame; avoid cropping."
        )
    if render_notes and "detail" in render_notes.lower():
        return "Framing: single-screen detail view with full layout visible."
    return "Framing: full-page capture in one frame."


def _extract_aspect_ratio(text: str) -> str | None:
    match = re.search(r"(\d{1,2})\s*[:x]\s*(\d{1,2})", text)
    if not match:
        return None
    ratio = f"{match.group(1)}:{match.group(2)}"
    return _normalize_aspect_ratio(ratio)


def _normalize_aspect_ratio(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower().replace(" ", "").replace("x", ":")
    return cleaned if cleaned in ALLOWED_ASPECT_RATIOS else None


def _normalize_image_size(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper()
    return cleaned if cleaned in ALLOWED_IMAGE_SIZES else None


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _truncate_error(value: str, limit: int = 240) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _write_redesign_preview(run_dir: Path, result: RedesignResult) -> None:
    redesign_dir = run_dir / "redesign"
    ensure_dir(redesign_dir)
    data = result.model_dump(mode="json")
    html = _build_preview_html(data)
    (redesign_dir / "index.html").write_text(html, encoding="utf-8")


def _build_preview_html(data: dict) -> str:
    payload = json.dumps(data, indent=2, ensure_ascii=True)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>UXAudit Redesign Preview</title>
    <style>
      @import url("https://fonts.googleapis.com/css2?family=Fraunces:wght@500;700&family=Space+Grotesk:wght@400;600&display=swap");

      :root {{
        --bg: #f4f1ea;
        --bg-accent: #dfeceb;
        --ink: #1f2a2e;
        --muted: #5b6b6f;
        --card: #ffffff;
        --accent: #e07a5f;
        --accent-2: #2c5a5d;
        --ring: rgba(44, 90, 93, 0.2);
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        font-family: "Space Grotesk", "Segoe UI", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at top, var(--bg-accent), var(--bg));
        min-height: 100vh;
      }}

      .wrap {{
        max-width: 1360px;
        margin: 0 auto;
        padding: 48px 24px 80px;
      }}

      header {{
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-bottom: 32px;
      }}

      .eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.2em;
        font-size: 12px;
        color: var(--accent-2);
      }}

      h1 {{
        font-family: "Fraunces", serif;
        font-size: 40px;
        margin: 0;
      }}

      .summary {{
        color: var(--muted);
        max-width: 680px;
        font-size: 16px;
      }}

      .hint {{
        color: var(--accent-2);
        font-size: 13px;
      }}

      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 20px;
      }}

      .card {{
        background: var(--card);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 20px 40px rgba(31, 42, 46, 0.08);
        border: 1px solid rgba(31, 42, 46, 0.06);
        display: flex;
        flex-direction: column;
        gap: 12px;
        animation: fadeUp 0.6s ease both;
      }}

      .card img {{
        width: 100%;
        border-radius: 14px;
        border: 1px solid rgba(31, 42, 46, 0.08);
        object-fit: cover;
        background: #f1f1f1;
      }}

      .card h3 {{
        margin: 0;
        font-size: 18px;
      }}

      .meta {{
        color: var(--muted);
        font-size: 14px;
      }}

      .pill {{
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        background: rgba(224, 122, 95, 0.14);
        color: var(--accent-2);
      }}

      .source {{
        margin-bottom: 36px;
        padding: 16px;
        border-radius: 18px;
        border: 1px dashed rgba(44, 90, 93, 0.3);
        background: rgba(255, 255, 255, 0.75);
      }}

      .source img {{
        width: 100%;
        border-radius: 12px;
      }}

      .chips {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .viewer {{
        display: grid;
        grid-template-columns: minmax(0, 1.7fr) minmax(260px, 0.9fr);
        gap: 24px;
        align-items: start;
      }}

      .viewer-main {{
        background: var(--card);
        border-radius: 24px;
        padding: 20px;
        box-shadow: 0 24px 50px rgba(31, 42, 46, 0.1);
        border: 1px solid rgba(31, 42, 46, 0.06);
      }}

      .viewer-image-wrap {{
        position: relative;
        border-radius: 18px;
        padding: 12px;
        border: 1px solid rgba(31, 42, 46, 0.08);
        background: #f6f4ef;
      }}

      .viewer-image-wrap a {{
        display: block;
        border-radius: 12px;
      }}

      .viewer-image-wrap a:focus {{
        outline: none;
        box-shadow: 0 0 0 3px var(--ring);
      }}

      .viewer-image {{
        width: 100%;
        max-height: 70vh;
        object-fit: contain;
        border-radius: 12px;
        display: block;
        background: #f1f1f1;
      }}

      .viewer-badge {{
        position: absolute;
        top: 16px;
        left: 16px;
        padding: 6px 12px;
        border-radius: 999px;
        font-size: 12px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        background: rgba(224, 122, 95, 0.18);
        color: var(--accent-2);
      }}

      .viewer-info {{
        margin-top: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }}

      .viewer-title {{
        font-size: 24px;
        font-weight: 600;
      }}

      .viewer-meta {{
        color: var(--muted);
        font-size: 14px;
      }}

      .viewer-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}

      .viewer-actions button,
      .viewer-actions a {{
        border: 1px solid rgba(31, 42, 46, 0.15);
        background: #ffffff;
        color: var(--ink);
        border-radius: 999px;
        padding: 8px 14px;
        font-size: 13px;
        cursor: pointer;
        text-decoration: none;
      }}

      .viewer-actions button:hover,
      .viewer-actions a:hover {{
        border-color: var(--accent);
      }}

      .viewer-text p {{
        margin: 0;
        color: var(--muted);
      }}

      .detail-block {{
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid rgba(31, 42, 46, 0.08);
      }}

      .detail-label {{
        font-size: 11px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent-2);
        margin-bottom: 6px;
      }}

      .detail-block ul {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
      }}

      details summary {{
        cursor: pointer;
        font-weight: 600;
        color: var(--ink);
      }}

      .prompt {{
        margin-top: 8px;
        padding: 10px 12px;
        background: #f4f1ea;
        border-radius: 12px;
        font-size: 13px;
        color: var(--ink);
        white-space: pre-wrap;
      }}

      .viewer-list {{
        display: flex;
        flex-direction: column;
        gap: 12px;
        position: sticky;
        top: 24px;
      }}

      .list-header {{
        font-weight: 600;
        font-size: 14px;
        color: var(--accent-2);
      }}

      .list {{
        display: flex;
        flex-direction: column;
        gap: 12px;
      }}

      .list-item {{
        display: flex;
        gap: 12px;
        align-items: center;
        padding: 10px;
        border-radius: 16px;
        border: 1px solid rgba(31, 42, 46, 0.08);
        background: var(--card);
        cursor: pointer;
        text-align: left;
      }}

      .list-item.active {{
        border-color: var(--accent);
        box-shadow: 0 0 0 3px var(--ring);
      }}

      .list-item img {{
        width: 88px;
        height: 64px;
        border-radius: 12px;
        object-fit: cover;
        border: 1px solid rgba(31, 42, 46, 0.08);
        background: #f1f1f1;
      }}

      .list-title {{
        font-weight: 600;
        font-size: 14px;
      }}

      .list-meta {{
        font-size: 12px;
        color: var(--muted);
      }}

      @keyframes fadeUp {{
        from {{
          opacity: 0;
          transform: translateY(12px);
        }}
        to {{
          opacity: 1;
          transform: translateY(0);
        }}
      }}

      @media (max-width: 720px) {{
        h1 {{
          font-size: 30px;
        }}
        .wrap {{
          padding: 32px 18px 64px;
        }}
        .viewer {{
          grid-template-columns: 1fr;
        }}
        .viewer-list {{
          position: static;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <header>
        <div class="eyebrow">Redesign Preview</div>
        <h1>Visual Concepts</h1>
        <div class="summary" id="summary"></div>
        <div class="hint" id="hint"></div>
      </header>
      <section class="viewer">
        <div class="viewer-main">
          <div class="viewer-image-wrap">
            <div class="viewer-badge" id="viewer-badge"></div>
            <a id="viewer-open" href="#" target="_blank" rel="noopener">
              <img id="viewer-image" class="viewer-image" alt="Preview image" />
            </a>
          </div>
          <div class="viewer-info">
            <div class="viewer-title" id="viewer-title"></div>
            <div class="viewer-meta" id="viewer-meta"></div>
            <div class="chips" id="viewer-palette"></div>
            <div class="viewer-text" id="viewer-text"></div>
            <div class="viewer-actions">
              <button id="viewer-prev" type="button">Prev</button>
              <button id="viewer-next" type="button">Next</button>
              <button id="viewer-base" type="button">Base</button>
              <a id="viewer-open-link" href="#" target="_blank" rel="noopener">Open image</a>
            </div>
          </div>
        </div>
        <aside class="viewer-list">
          <div class="list-header">Quick switch</div>
          <div class="list" id="concept-list"></div>
        </aside>
      </section>
    </div>
    <script>
      const data = {payload};
      const summary = document.getElementById("summary");
      const hint = document.getElementById("hint");
      const list = document.getElementById("concept-list");
      const viewerImage = document.getElementById("viewer-image");
      const viewerOpen = document.getElementById("viewer-open");
      const viewerOpenLink = document.getElementById("viewer-open-link");
      const viewerTitle = document.getElementById("viewer-title");
      const viewerMeta = document.getElementById("viewer-meta");
      const viewerText = document.getElementById("viewer-text");
      const viewerPalette = document.getElementById("viewer-palette");
      const viewerBadge = document.getElementById("viewer-badge");
      const prevBtn = document.getElementById("viewer-prev");
      const nextBtn = document.getElementById("viewer-next");
      const baseBtn = document.getElementById("viewer-base");

      const firstSummary =
        data.analysis && data.analysis.items && data.analysis.items[0]
          ? data.analysis.items[0].summary
          : "";
      summary.textContent =
        firstSummary ||
        "Four distinct directions generated from the captured UI.";
      hint.textContent =
        "Click a tile to view full size. Use Left/Right keys to cycle.";

      const toPreviewPath = (path) => {{
        if (!path) return "";
        if (path.startsWith("redesign/")) return path.replace("redesign/", "");
        return "../" + path;
      }};

      const placeholder =
        "data:image/svg+xml;charset=utf-8," +
        encodeURIComponent(
          '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">' +
            '<rect width="100%" height="100%" fill="#f1f1f1"/>' +
            '<text x="50%" y="50%" text-anchor="middle" fill="#8a8a8a" font-family="Arial" font-size="20">Render pending</text>' +
          "</svg>"
        );

      const items = [];
      const listNodes = [];
      const shots = data.screenshots || [];
      const concepts = data.concepts || [];

      shots.forEach((shot, index) => {{
        items.push({{
          kind: "base",
          title: "Base screenshot " + (index + 1),
          image: toPreviewPath(shot.path),
          metaParts: [shot.id, shot.path].filter(Boolean),
          badge: "BASE",
        }});
      }});

      concepts.forEach((concept, index) => {{
        items.push({{
          kind: "concept",
          title: concept.title || "Concept " + (index + 1),
          image: toPreviewPath(concept.image_path),
          metaParts: [
            concept.id,
            concept.visual_style,
            concept.render_aspect_ratio,
            concept.render_image_size,
            concept.render_frame,
            concept.rendered ? "rendered" : "pending",
          ].filter(Boolean),
          badge: "CONCEPT " + (index + 1) + "/" + concepts.length,
          concept: concept,
        }});
      }});

      const escapeHtml = (value) => {{
        return String(value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/\"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }};

      const detailList = (label, values) => {{
        if (!values || !values.length) return "";
        let html =
          '<div class="detail-block"><div class="detail-label">' +
          escapeHtml(label) +
          "</div><ul>";
        values.forEach((item) => {{
          html += "<li>" + escapeHtml(item) + "</li>";
        }});
        html += "</ul></div>";
        return html;
      }};

      const buildDetail = (item) => {{
        if (item.kind === "base") {{
          return (
            '<div class="detail-block"><div class="detail-label">Base</div>' +
            '<div class="meta">Captured page reference for renders.</div></div>'
          );
        }}
        const concept = item.concept || {{}};
        let html = "";
        const renderMeta = [
          concept.render_frame ? "Frame: " + concept.render_frame : "",
          concept.render_aspect_ratio ? "Aspect: " + concept.render_aspect_ratio : "",
          concept.render_image_size ? "Size: " + concept.render_image_size : "",
        ].filter(Boolean);
        if (renderMeta.length) {{
          html +=
            '<div class="detail-block"><div class="detail-label">Render</div>' +
            '<div class="meta">' +
            escapeHtml(renderMeta.join(" · ")) +
            "</div></div>";
        }}
        if (concept.narrative) {{
          html += "<p>" + escapeHtml(concept.narrative) + "</p>";
        }}
        html += detailList("Experience goals", concept.experience_goals || []);
        html += detailList("Layout changes", concept.layout_changes || []);
        html += detailList("Component changes", concept.component_changes || []);
        if (concept.image_prompt) {{
          html +=
            '<details class="detail-block"><summary>Prompt</summary>' +
            '<div class="prompt">' +
            escapeHtml(concept.image_prompt) +
            "</div></details>";
        }}
        return html;
      }};

      const renderPalette = (item) => {{
        const palette =
          item.kind === "concept" && item.concept && item.concept.palette
            ? item.concept.palette
            : [];
        viewerPalette.innerHTML = "";
        if (!palette.length) {{
          viewerPalette.style.display = "none";
          return;
        }}
        viewerPalette.style.display = "flex";
        palette.slice(0, 6).forEach((color) => {{
          const chip = document.createElement("span");
          chip.className = "pill";
          chip.textContent = color;
          viewerPalette.appendChild(chip);
        }});
      }};

      let activeIndex = 0;

      const setActive = (index) => {{
        if (!items.length) return;
        activeIndex = (index + items.length) % items.length;
        const item = items[activeIndex];
        const imageSrc = item.image || placeholder;
        viewerImage.src = imageSrc;
        viewerImage.alt = item.title;
        viewerOpen.href = imageSrc;
        viewerOpenLink.href = imageSrc;
        viewerTitle.textContent = item.title;
        viewerBadge.textContent = item.badge || "";
        viewerMeta.textContent = item.metaParts.join(" · ");
        viewerText.innerHTML = buildDetail(item);
        renderPalette(item);
        listNodes.forEach((node, idx) => {{
          node.classList.toggle("active", idx === activeIndex);
        }});
      }};

      const addListItem = (item, index) => {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "list-item";
        const thumb = document.createElement("img");
        thumb.src = item.image || placeholder;
        thumb.alt = item.title;
        thumb.onerror = () => {{
          thumb.src = placeholder;
        }};
        const label = document.createElement("div");
        const title = document.createElement("div");
        title.className = "list-title";
        title.textContent = item.title;
        const meta = document.createElement("div");
        meta.className = "list-meta";
        if (item.kind === "base") {{
          meta.textContent = "Base";
        }} else {{
          const metaBits = [
            item.concept.visual_style,
            item.concept.render_aspect_ratio,
          ].filter(Boolean);
          meta.textContent = metaBits.join(" · ") || item.concept.id || "";
        }}
        label.appendChild(title);
        label.appendChild(meta);
        button.appendChild(thumb);
        button.appendChild(label);
        button.addEventListener("click", () => setActive(index));
        list.appendChild(button);
        listNodes.push(button);
      }};

      items.forEach((item, index) => addListItem(item, index));

      viewerImage.onerror = () => {{
        viewerImage.src = placeholder;
      }};

      prevBtn.addEventListener("click", () => setActive(activeIndex - 1));
      nextBtn.addEventListener("click", () => setActive(activeIndex + 1));
      baseBtn.addEventListener("click", () => {{
        const baseIndex = items.findIndex((item) => item.kind === "base");
        if (baseIndex >= 0) {{
          setActive(baseIndex);
        }}
      }});

      document.addEventListener("keydown", (event) => {{
        if (event.key === "ArrowRight") {{
          setActive(activeIndex + 1);
        }}
        if (event.key === "ArrowLeft") {{
          setActive(activeIndex - 1);
        }}
      }});

      const firstConceptIndex = items.findIndex(
        (item) => item.kind === "concept"
      );
      setActive(firstConceptIndex >= 0 ? firstConceptIndex : 0);
    </script>
  </body>
</html>
"""


def _resolve_auth(config: AuditConfig, settings: Settings) -> AuthConfig | None:
    if config.auth is None:
        return None
    if config.auth.mode == "none":
        return None
    if config.auth.username is None and settings.auth_username:
        config.auth.username = settings.auth_username
    if config.auth.password is None and settings.auth_password:
        config.auth.password = settings.auth_password
    return config.auth


def _storage_state_path(auth: AuthConfig | None) -> Path | None:
    if not auth:
        return None
    if auth.mode == "storage_state":
        if not auth.storage_state_path:
            raise ValueError(
                "auth.storage_state_path is required for storage_state mode"
            )
        return auth.storage_state_path
    return None


def _http_credentials(auth: AuthConfig | None):
    if not auth or auth.mode != "basic":
        return None
    if not auth.username or not auth.password:
        raise ValueError("auth.username and auth.password are required for basic auth")
    return {"username": auth.username, "password": auth.password}


def _auth_storage_state_for_report(
    auth: AuthConfig,
    auth_result: AuthResult,
    run_dir: Path,
) -> str | None:
    if auth_result.storage_state_path:
        try:
            return str(auth_result.storage_state_path.relative_to(run_dir))
        except ValueError:
            return str(auth_result.storage_state_path)
    if auth.storage_state_path:
        return str(auth.storage_state_path)
    return None


def _validate_redesign_limits(config: AuditConfig, variants: int) -> None:
    if variants < 1:
        raise ValueError("variants must be at least 1")
    if config.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if config.max_total_screenshots < 1:
        raise ValueError("max_total_screenshots must be at least 1")
    if config.max_total_screenshots < config.max_pages:
        raise ValueError("max_total_screenshots must be >= max_pages")
