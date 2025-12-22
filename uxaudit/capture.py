from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from uxaudit.browser import BrowserConfig, browser_page
from uxaudit.config import AuditConfig


@dataclass
class CaptureResult:
    url: str
    title: str
    path: Path
    links: list[str]


def capture_full_page(url: str, output_path: Path, config: AuditConfig) -> CaptureResult:
    browser_config = BrowserConfig(
        viewport_width=config.viewport_width,
        viewport_height=config.viewport_height,
        user_agent=config.user_agent,
    )
    with browser_page(browser_config) as page:
        page.goto(url, wait_until=config.wait_until, timeout=config.timeout_ms)
        title = page.title()
        links = _extract_nav_links(page)
        page.screenshot(path=str(output_path), full_page=True)
        return CaptureResult(url=page.url, title=title, path=output_path, links=links)


def _extract_nav_links(page: Page) -> list[str]:
    script = """
() => {
  const selector = 'nav a[href], header a[href], footer a[href]';
  return Array.from(document.querySelectorAll(selector))
    .map((el) => el.href)
    .filter((href) => href && typeof href === 'string');
}
"""
    try:
        links = page.evaluate(script)
    except Exception:
        return []
    if not isinstance(links, list):
        return []
    return [link for link in links if isinstance(link, str) and link]
