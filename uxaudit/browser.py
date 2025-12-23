from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright


@dataclass
class BrowserConfig:
    viewport_width: int
    viewport_height: int
    user_agent: str | None = None
    headless: bool = True


@contextmanager
def browser_page(config: BrowserConfig) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        page = browser.new_page(
            viewport={"width": config.viewport_width, "height": config.viewport_height},
            user_agent=config.user_agent,
        )
        try:
            yield page
        finally:
            page.close()
            browser.close()
