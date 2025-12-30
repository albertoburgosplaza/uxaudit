from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import HttpCredentials

from uxaudit.aggregate import normalize_recommendations
from uxaudit.auth import AuthResult, perform_login
from uxaudit.browser import BrowserConfig, browser_context
from uxaudit.capture import capture_full_page
from uxaudit.config import AuditConfig, AuthConfig, Settings
from uxaudit.crawler import filter_links, normalize_url
from uxaudit.gemini_client import GeminiClient
from uxaudit.prompts import build_consistency_prompt, build_prompt
from uxaudit.report import write_json
from uxaudit.schema import (
    AuditResult,
    AuthState,
    AuthSummary,
    Manifest,
    PageTarget,
    ScreenshotArtifact,
    SectionTarget,
)
from uxaudit.utils import build_run_id, ensure_dir

logger = logging.getLogger(__name__)


def run_audit(config: AuditConfig, settings: Settings) -> tuple[AuditResult, Path]:
    _validate_limits(config)

    run_id = build_run_id()
    run_dir = config.output_dir / run_id
    screenshots_dir = run_dir / "screenshots"
    ensure_dir(screenshots_dir)

    started_at = datetime.now(timezone.utc)

    client = GeminiClient(api_key=settings.api_key or "", model=config.model)

    pages: list[PageTarget] = []
    sections: list[SectionTarget] = []
    screenshots: list[ScreenshotArtifact] = []
    recommendations = []
    analysis_items: list[dict] = []
    raw_responses: list[str] = []

    page_counter = 0
    remaining_screenshots = config.max_total_screenshots

    auth = _resolve_auth(config, settings)
    auth_enabled = auth is not None
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
        section: SectionTarget | None = None,
        auth_state: AuthState | None = None,
    ) -> None:
        prompt = build_prompt(page, screenshot.id, section, auth_state)
        analysis, raw_response = client.analyze_image(prompt, image_path)
        recommendations.extend(normalize_recommendations(analysis))
        analysis_items.append(
            {
                "page_id": page.id,
                "section_id": section.id if section else None,
                "screenshot_id": screenshot.id,
                "url": page.url,
                "title": page.title,
                "section_title": section.title if section else None,
                "auth_state": auth_state,
                "analysis": analysis if isinstance(analysis, dict) else None,
            }
        )
        if raw_response:
            raw_responses.append(raw_response)

    def capture_page(
        context,
        url: str,
        auth_state: AuthState,
        allow_sections: bool,
    ) -> tuple[str, list[str]] | None:
        nonlocal page_counter, remaining_screenshots
        if remaining_screenshots <= 0:
            return None

        page_counter += 1
        screenshot_path = screenshots_dir / f"page-{page_counter}.png"
        max_sections = 0
        if allow_sections:
            max_sections = min(
                config.max_sections_per_page, max(remaining_screenshots - 1, 0)
            )

        try:
            capture = capture_full_page(
                url,
                screenshot_path,
                config,
                max_sections=max_sections,
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

        analyze_and_collect(page, screenshot, screenshot_path, None, auth_state)

        for section_index, section_capture in enumerate(capture.sections, start=1):
            if remaining_screenshots <= 0:
                break
            section = SectionTarget(
                id=f"section-{page_counter}-{section_index}",
                page_id=page.id,
                title=section_capture.title,
                selector=section_capture.selector,
                auth_state=auth_state,
            )
            sections.append(section)
            section_shot = ScreenshotArtifact(
                id=f"shot-{page_counter}-s{section_index}",
                page_id=page.id,
                section_id=section.id,
                path=str(section_capture.path.relative_to(run_dir)),
                kind="section",
                width=section_capture.width,
                height=section_capture.height,
                auth_state=auth_state,
            )
            screenshots.append(section_shot)
            remaining_screenshots -= 1
            analyze_and_collect(
                page, section_shot, section_capture.path, section, auth_state
            )

        return capture.url, capture.links

    if auth_enabled:
        if remaining_screenshots < 2:
            raise ValueError(
                "Authentication requires at least 2 screenshots for pre/post login capture"
            )
        with browser_context(browser_config) as context:
            capture_page(context, config.url, "pre_login", allow_sections=False)

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

            result = capture_page(context, url, auth_state, allow_sections=True)
            if result is None:
                continue
            pages_in_crawl += 1

            _, links = result
            for link in filter_links(links, config.url):
                if link not in seen:
                    queue.append(link)

    if not pages:
        raise RuntimeError("No pages were captured. Check the URL and try again.")

    if config.style_consistency:
        consistency_recs, consistency_items, consistency_raw = _run_style_consistency(
            client=client,
            pages=pages,
            sections=sections,
            screenshots=screenshots,
            run_dir=run_dir,
            batch_size=config.style_consistency_batch_size,
        )
        if consistency_recs:
            recommendations.extend(consistency_recs)
        if consistency_items:
            analysis_items.extend(consistency_items)
        if consistency_raw:
            raw_responses.extend(consistency_raw)

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
        sections=sections,
        screenshots=screenshots,
        auth=auth_summary,
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
        auth=auth_summary,
    )
    write_json(run_dir / "report.json", report)

    return report, run_dir


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


def _http_credentials(auth: AuthConfig | None) -> HttpCredentials | None:
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


def _run_style_consistency(
    client: GeminiClient,
    pages: list[PageTarget],
    sections: list[SectionTarget],
    screenshots: list[ScreenshotArtifact],
    run_dir: Path,
    batch_size: int,
) -> tuple[list, list[dict], list[str]]:
    if len(screenshots) < 2:
        return [], [], []

    batch_size = max(batch_size, 2)
    anchors = _select_style_consistency_anchors(screenshots, batch_size)
    anchor_ids = {shot.id for shot in anchors}

    page_by_id = {page.id: page for page in pages}
    section_by_id = {section.id: section for section in sections}

    contexts: dict[str, dict[str, object]] = {}
    for shot in screenshots:
        page = page_by_id.get(shot.page_id)
        section = section_by_id.get(shot.section_id) if shot.section_id else None
        contexts[shot.id] = {
            "path": run_dir / shot.path,
            "page_url": _clean_prompt_text(page.url if page else ""),
            "page_title": _clean_prompt_text(page.title if page else ""),
            "section_title": _clean_prompt_text(section.title if section else ""),
            "section_selector": _clean_prompt_text(section.selector if section else ""),
        }

    recommendations: list = []
    analysis_items: list[dict] = []
    raw_responses: list[str] = []

    batches = _build_style_consistency_batches(
        screenshots, anchors, batch_size, anchor_ids
    )
    for batch_index, batch in enumerate(batches, start=1):
        shots_block = _build_style_consistency_block(batch, contexts, anchor_ids)
        prompt = build_consistency_prompt(shots_block)
        image_paths = [contexts[shot.id]["path"] for shot in batch]
        analysis, raw_response = client.analyze_images(prompt, image_paths)
        recommendations.extend(normalize_recommendations(analysis))
        analysis_items.append(
            {
                "analysis_type": "style_consistency",
                "batch_index": batch_index,
                "screenshot_ids": [shot.id for shot in batch],
                "auth_states": sorted(
                    {shot.auth_state for shot in batch if shot.auth_state}
                ),
                "analysis": analysis if isinstance(analysis, dict) else None,
            }
        )
        if raw_response:
            raw_responses.append(raw_response)

    return recommendations, analysis_items, raw_responses


def _select_style_consistency_anchors(
    screenshots: list[ScreenshotArtifact],
    batch_size: int,
) -> list[ScreenshotArtifact]:
    anchors: list[ScreenshotArtifact] = []
    for auth_state in ("pre_login", "authenticated"):
        for shot in screenshots:
            if shot.auth_state == auth_state and shot.kind == "full_page":
                anchors.append(shot)
                break
    if not anchors and screenshots:
        anchors.append(screenshots[0])
    if len(anchors) > batch_size:
        return anchors[:batch_size]
    return anchors


def _build_style_consistency_batches(
    screenshots: list[ScreenshotArtifact],
    anchors: list[ScreenshotArtifact],
    batch_size: int,
    anchor_ids: set[str],
) -> list[list[ScreenshotArtifact]]:
    remaining = [shot for shot in screenshots if shot.id not in anchor_ids]
    if not remaining:
        return [anchors] if anchors else []
    per_batch = max(batch_size - len(anchors), 1)
    batches: list[list[ScreenshotArtifact]] = []
    for chunk in _chunked(remaining, per_batch):
        batches.append(anchors + chunk)
    return batches


def _build_style_consistency_block(
    shots: list[ScreenshotArtifact],
    contexts: dict[str, dict[str, object]],
    anchor_ids: set[str],
) -> str:
    lines = []
    for shot in shots:
        context = contexts[shot.id]
        section_title = context.get("section_title") or ""
        section_selector = context.get("section_selector") or ""
        section_label = section_title or section_selector or "n/a"
        page_url = context.get("page_url") or "n/a"
        page_title = context.get("page_title") or "n/a"
        auth_state = shot.auth_state or "unknown"
        baseline = "yes" if shot.id in anchor_ids else "no"
        lines.append(
            " | ".join(
                [
                    f"- screenshot_id: {shot.id}",
                    f"auth_state: {auth_state}",
                    f"kind: {shot.kind}",
                    f"baseline: {baseline}",
                    f"page_url: {page_url}",
                    f"page_title: {page_title}",
                    f"section: {section_label}",
                ]
            )
        )
    return "\n".join(lines)


def _chunked(
    items: list[ScreenshotArtifact],
    size: int,
) -> list[list[ScreenshotArtifact]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _clean_prompt_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())


def _validate_limits(config: AuditConfig) -> None:
    if config.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if config.max_total_screenshots < 1:
        raise ValueError("max_total_screenshots must be at least 1")
    if config.max_sections_per_page < 0:
        raise ValueError("max_sections_per_page must be at least 0")
    if config.style_consistency and config.style_consistency_batch_size < 2:
        raise ValueError("style_consistency_batch_size must be at least 2")
