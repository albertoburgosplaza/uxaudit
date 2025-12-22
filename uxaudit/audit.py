from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

from uxaudit.aggregate import normalize_recommendations
from uxaudit.capture import capture_full_page
from uxaudit.config import AuditConfig, Settings
from uxaudit.crawler import filter_links, normalize_url
from uxaudit.gemini_client import GeminiClient
from uxaudit.prompts import build_prompt
from uxaudit.report import write_json
from uxaudit.schema import (
    AuditResult,
    Manifest,
    PageTarget,
    ScreenshotArtifact,
    SectionTarget,
)
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
    sections: list[SectionTarget] = []
    screenshots: list[ScreenshotArtifact] = []
    recommendations = []
    analysis_items: list[dict] = []
    raw_responses: list[str] = []

    def _analyze_with_retry(prompt: str, image_path: Path) -> tuple[dict | list, str]:
        last_error: Exception | None = None
        for attempt in range(config.analysis_max_attempts):
            try:
                return _execute_with_timeout(
                    lambda: client.analyze_image(prompt, image_path),
                    config.analysis_timeout_s,
                )
            except Exception as exc:  # noqa: PERF203
                last_error = exc
                logger.warning(
                    "Analysis attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    config.analysis_max_attempts,
                    image_path,
                    exc,
                )
                if attempt < config.analysis_max_attempts - 1:
                    sleep(config.analysis_backoff_seconds * (attempt + 1))
        assert last_error is not None
        raise last_error

    def analyze_and_collect(
        page: PageTarget,
        screenshot: ScreenshotArtifact,
        image_path: Path,
        section: SectionTarget | None = None,
    ) -> bool:
        prompt = build_prompt(page, screenshot.id, section)
        try:
            analysis, raw_response = _analyze_with_retry(prompt, image_path)
        except Exception as exc:  # noqa: PERF203
            target = section or page
            target.status = "analysis_failed"
            target.error = str(exc)
            return False

        recommendations.extend(normalize_recommendations(analysis))
        analysis_items.append(
            {
                "page_id": page.id,
                "section_id": section.id if section else None,
                "screenshot_id": screenshot.id,
                "url": page.url,
                "title": page.title,
                "section_title": section.title if section else None,
                "analysis": analysis if isinstance(analysis, dict) else None,
            }
        )
        if raw_response:
            raw_responses.append(raw_response)
        return True

    while queue and len(pages) < max_pages:
        if len(screenshots) >= config.max_total_screenshots:
            break
        url = queue.popleft()
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)

        page_index = len(pages) + 1
        screenshot_path = screenshots_dir / f"page-{page_index}.png"
        remaining = config.max_total_screenshots - len(screenshots)
        max_sections = min(config.max_sections_per_page, max(remaining - 1, 0))
        capture = None
        capture_error: Exception | None = None
        for attempt in range(config.capture_max_attempts):
            try:
                capture = capture_full_page(
                    url,
                    screenshot_path,
                    config,
                    max_sections=max_sections,
                )
                break
            except Exception as exc:  # noqa: PERF203
                capture_error = exc
                logger.warning(
                    "Capture attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    config.capture_max_attempts,
                    url,
                    exc,
                )
                if attempt < config.capture_max_attempts - 1:
                    sleep(config.capture_backoff_seconds * (attempt + 1))

        page = PageTarget(
            id=f"page-{page_index}",
            url=capture.url if capture else url,
            title=capture.title if capture else None,
            status="captured" if capture else "capture_failed",
            error=str(capture_error) if capture_error else None,
        )
        pages.append(page)

        if not capture:
            continue

        screenshot = ScreenshotArtifact(
            id=f"shot-{page_index}",
            page_id=page.id,
            path=str(screenshot_path.relative_to(run_dir)),
            width=config.viewport_width,
            height=config.viewport_height,
        )
        screenshots.append(screenshot)

        analyze_and_collect(page, screenshot, screenshot_path, None)

        for section_index, section_capture in enumerate(capture.sections, start=1):
            section = SectionTarget(
                id=f"section-{page_index}-{section_index}",
                page_id=page.id,
                title=section_capture.title,
                selector=section_capture.selector,
                status="captured",
            )
            sections.append(section)
            section_shot = ScreenshotArtifact(
                id=f"shot-{page_index}-s{section_index}",
                page_id=page.id,
                section_id=section.id,
                path=str(section_capture.path.relative_to(run_dir)),
                kind="section",
                width=section_capture.width,
                height=section_capture.height,
            )
            screenshots.append(section_shot)
            analyze_and_collect(page, section_shot, section_capture.path, section)

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
        sections=sections,
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
        sections=sections,
        screenshots=screenshots,
        recommendations=recommendations,
        analysis={"items": analysis_items} if analysis_items else None,
        raw_response=raw_responses or None,
    )
    write_json(run_dir / "report.json", report)

    return report, run_dir


def _validate_limits(config: AuditConfig) -> None:
    if config.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if config.max_total_screenshots < 1:
        raise ValueError("max_total_screenshots must be at least 1")
    if config.max_sections_per_page < 0:
        raise ValueError("max_sections_per_page must be at least 0")
    if config.capture_max_attempts < 1:
        raise ValueError("capture_max_attempts must be at least 1")
    if config.capture_backoff_seconds < 0:
        raise ValueError("capture_backoff_seconds must be non-negative")
    if config.analysis_max_attempts < 1:
        raise ValueError("analysis_max_attempts must be at least 1")
    if config.analysis_backoff_seconds < 0:
        raise ValueError("analysis_backoff_seconds must be non-negative")
    if config.analysis_timeout_s <= 0:
        raise ValueError("analysis_timeout_s must be greater than 0")


def _execute_with_timeout(callable_obj, timeout_s: float):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callable_obj)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeoutError as exc:  # noqa: PERF203
            future.cancel()
            raise TimeoutError(f"Operation timed out after {timeout_s} seconds") from exc
