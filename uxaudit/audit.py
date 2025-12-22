from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from uxaudit.aggregate import normalize_recommendations
from uxaudit.capture import capture_full_page
from uxaudit.config import AuditConfig, Settings
from uxaudit.crawler import filter_links, normalize_url
from uxaudit.gemini_client import GeminiClient
from uxaudit.prompts import build_prompt
from uxaudit.report import write_json
from uxaudit.schema import AuditResult, Manifest, PageTarget, ScreenshotArtifact
from uxaudit.utils import build_run_id, ensure_dir

logger = logging.getLogger(__name__)


def run_audit(config: AuditConfig, settings: Settings) -> tuple[AuditResult, Path]:
    _validate_limits(config)

    max_pages = min(config.max_pages, config.max_total_screenshots)
    run_id = build_run_id()
    run_dir = config.output_dir / run_id
    screenshots_dir = run_dir / "screenshots"
    ensure_dir(screenshots_dir)

    started_at = datetime.now(timezone.utc)

    client = GeminiClient(api_key=settings.api_key or "", model=config.model)

    queue = deque([config.url])
    seen: set[str] = set()
    pages: list[PageTarget] = []
    screenshots: list[ScreenshotArtifact] = []
    recommendations = []
    analysis_pages: list[dict] = []
    raw_responses: list[str] = []

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)

        page_index = len(pages) + 1
        screenshot_path = screenshots_dir / f"page-{page_index}.png"
        try:
            capture = capture_full_page(url, screenshot_path, config)
        except Exception as exc:
            logger.warning("Failed to capture %s: %s", url, exc)
            continue

        page = PageTarget(id=f"page-{page_index}", url=capture.url, title=capture.title)
        screenshot = ScreenshotArtifact(
            id=f"shot-{page_index}",
            page_id=page.id,
            path=str(screenshot_path.relative_to(run_dir)),
            width=config.viewport_width,
            height=config.viewport_height,
        )
        pages.append(page)
        screenshots.append(screenshot)

        prompt = build_prompt(page, screenshot.id)
        analysis, raw_response = client.analyze_image(prompt, screenshot_path)
        recommendations.extend(normalize_recommendations(analysis))
        analysis_pages.append(
            {
                "page_id": page.id,
                "url": page.url,
                "title": page.title,
                "analysis": analysis if isinstance(analysis, dict) else None,
            }
        )
        if raw_response:
            raw_responses.append(raw_response)

        links = filter_links(capture.links, config.url)
        for link in links:
            if link not in seen:
                queue.append(link)

    if not pages:
        raise RuntimeError("No pages were captured. Check the URL and try again.")

    manifest = Manifest(
        run_id=run_id,
        url=config.url,
        model=config.model,
        started_at=started_at,
        pages=pages,
        screenshots=screenshots,
    )
    write_json(run_dir / "manifest.json", manifest)

    completed_at = datetime.now(timezone.utc)
    report = AuditResult(
        run_id=run_id,
        url=config.url,
        model=config.model,
        started_at=started_at,
        completed_at=completed_at,
        pages=pages,
        screenshots=screenshots,
        recommendations=recommendations,
        analysis={"pages": analysis_pages} if analysis_pages else None,
        raw_response=raw_responses or None,
    )
    write_json(run_dir / "report.json", report)

    return report, run_dir


def _validate_limits(config: AuditConfig) -> None:
    if config.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if config.max_total_screenshots < 1:
        raise ValueError("max_total_screenshots must be at least 1")
