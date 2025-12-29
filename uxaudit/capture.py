from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, ElementHandle, Page

from uxaudit.browser import BrowserConfig, browser_page
from uxaudit.config import AuditConfig


@dataclass
class SectionCapture:
    title: str | None
    selector: str | None
    path: Path
    width: int
    height: int


@dataclass
class CaptureResult:
    url: str
    title: str
    path: Path
    links: list[str]
    sections: list[SectionCapture]


def capture_full_page(
    url: str,
    output_path: Path,
    config: AuditConfig,
    max_sections: int = 0,
    context: BrowserContext | None = None,
) -> CaptureResult:
    browser_config = BrowserConfig(
        viewport_width=config.viewport_width,
        viewport_height=config.viewport_height,
        user_agent=config.user_agent,
        headless=config.headless,
    )
    if context is None:
        with browser_page(browser_config) as page:
            return _capture_with_page(page, url, output_path, config, max_sections)

    page = context.new_page()
    try:
        return _capture_with_page(page, url, output_path, config, max_sections)
    finally:
        page.close()


def _capture_with_page(
    page: Page,
    url: str,
    output_path: Path,
    config: AuditConfig,
    max_sections: int,
) -> CaptureResult:
    page.goto(url, wait_until=config.wait_until, timeout=config.timeout_ms)
    title = page.title()
    links = _extract_nav_links(page)
    page.screenshot(path=str(output_path), full_page=True)
    sections: list[SectionCapture] = []
    if max_sections > 0:
        sections = _capture_sections(page, output_path, config, max_sections)
    return CaptureResult(
        url=page.url,
        title=title,
        path=output_path,
        links=links,
        sections=sections,
    )


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


def _capture_sections(
    page: Page,
    output_path: Path,
    config: AuditConfig,
    max_sections: int,
) -> list[SectionCapture]:
    candidates = _collect_section_candidates(page)
    min_width = config.viewport_width * 0.4
    min_height = 120
    max_height = config.viewport_height * 2.5
    seen: set[tuple[int, int, int, int]] = set()
    captures: list[SectionCapture] = []

    for element in candidates:
        if len(captures) >= max_sections:
            break
        box = element.bounding_box()
        if not box:
            continue
        width = int(box["width"])
        height = int(box["height"])
        if width < min_width or height < min_height:
            continue
        if height > max_height:
            continue
        signature = (round(box["x"]), round(box["y"]), width, height)
        if signature in seen:
            continue
        seen.add(signature)
        title = _section_title(element)
        selector = _section_selector(element)
        section_path = output_path.with_name(
            f"{output_path.stem}-section-{len(captures) + 1}.png"
        )
        try:
            element.screenshot(path=str(section_path))
        except Exception:
            continue
        captures.append(
            SectionCapture(
                title=title,
                selector=selector,
                path=section_path,
                width=width,
                height=height,
            )
        )
    return captures


def _collect_section_candidates(page: Page) -> list[ElementHandle]:
    selectors = [
        "section",
        "main",
        "article",
        "aside",
        "header",
        "footer",
        "[role='region']",
        "[role='main']",
        "[role='banner']",
        "[role='contentinfo']",
        "[aria-labelledby]",
    ]
    elements = list(page.query_selector_all(",".join(selectors)))
    headings = page.query_selector_all("h2, h3")
    for heading in headings:
        handle = heading.evaluate_handle(
            "el => el.closest('section, main, article, div')"
        )
        element = handle.as_element()
        if element:
            elements.append(element)
    return elements


def _section_title(element: ElementHandle) -> str | None:
    try:
        title = element.evaluate(
            """
            (el) => {
              const label = el.getAttribute('aria-label');
              if (label) return label.trim();
              const labelledby = el.getAttribute('aria-labelledby');
              if (labelledby) {
                const labelEl = document.getElementById(labelledby);
                if (labelEl && labelEl.textContent) {
                  return labelEl.textContent.trim();
                }
              }
              const heading = el.querySelector('h1, h2, h3');
              if (heading && heading.textContent) {
                return heading.textContent.trim();
              }
              return '';
            }
            """
        )
    except Exception:
        return None
    if not title:
        return None
    return str(title)


def _section_selector(element: ElementHandle) -> str | None:
    try:
        selector = element.evaluate(
            """
            (el) => {
              const tag = el.tagName.toLowerCase();
              if (el.id) return `${tag}#${el.id}`;
              if (el.classList && el.classList.length) {
                const classes = Array.from(el.classList).slice(0, 2).join('.');
                if (classes) return `${tag}.${classes}`;
              }
              return tag;
            }
            """
        )
    except Exception:
        return None
    if not selector:
        return None
    return str(selector)
