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
from uxaudit.prompts import build_prompt
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


def _validate_limits(config: AuditConfig) -> None:
    if config.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if config.max_total_screenshots < 1:
        raise ValueError("max_total_screenshots must be at least 1")
    if config.max_sections_per_page < 0:
        raise ValueError("max_sections_per_page must be at least 0")
