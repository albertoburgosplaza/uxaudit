from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, HttpCredentials, Page, sync_playwright


@dataclass
class BrowserConfig:
    viewport_width: int
    viewport_height: int
    user_agent: str | None = None
    headless: bool = True


@contextmanager
def browser_context(
    config: BrowserConfig,
    storage_state: Path | None = None,
    http_credentials: HttpCredentials | None = None,
) -> Iterator[BrowserContext]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        context = browser.new_context(
            viewport={"width": config.viewport_width, "height": config.viewport_height},
            user_agent=config.user_agent,
            storage_state=str(storage_state) if storage_state else None,
            http_credentials=http_credentials,
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()


@contextmanager
def browser_page(config: BrowserConfig) -> Iterator[Page]:
    with browser_context(config) as context:
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()
